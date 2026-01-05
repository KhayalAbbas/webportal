"""Company research worker for queued run processing."""

import argparse
import asyncio
import os
import socket
from datetime import datetime, timedelta
from typing import Optional

from app.db.session import get_async_session_context
from app.services.company_research_service import CompanyResearchService
from app.services.company_extraction_service import CompanyExtractionService
from app.services.company_source_extraction_service import CompanySourceExtractionService
from app.utils.time import utc_now


async def _handle_cancel(
    service: CompanyResearchService,
    job_id,
    tenant_id: str,
    run_id,
    reason: Optional[str] = None,
):
    run = await service.get_research_run(tenant_id, run_id)
    allow_status_update = run and run.status in {"queued", "running", "cancel_requested"}

    await service.repo.cancel_pending_steps(tenant_id, run_id, reason=reason or "cancelled")

    await service.mark_job_cancelled(job_id, last_error=reason)
    if allow_status_update:
        await service.repo.set_run_status(
            tenant_id,
            run_id,
            status="cancelled",
            last_error=reason,
            finished_at=utc_now(),
        )
    await service.append_event(
        tenant_id,
        run_id,
        "worker_cancelled",
        reason or "cancel requested",
        status="cancelled",
    )


async def _process_job(service: CompanyResearchService, job, worker_id: str) -> None:
    tenant_id = str(job.tenant_id)
    run_id = job.run_id

    run = await service.get_research_run(tenant_id, run_id)
    if not run:
        await service.mark_job_failed(job.id, "run_not_found", backoff_seconds=0)
        await service.append_event(tenant_id, run_id, "worker_failed", "Run not found", status="failed")
        await service.db.commit()
        return

    if job.cancel_requested or run.status == "cancel_requested":
        await _handle_cancel(service, job.id, tenant_id, run_id, reason="cancel requested")
        await service.db.commit()
        return

    job = await service.mark_job_running(job.id, worker_id)
    if not job:
        await service.append_event(tenant_id, run_id, "worker_failed", "Unable to mark job running", status="failed")
        await service.db.commit()
        return

    started_at = run.started_at or utc_now()
    await service.repo.set_run_status(
        tenant_id,
        run_id,
        status="running",
        last_error=None,
        started_at=started_at,
    )
    await service.append_event(tenant_id, run_id, "worker_claimed", f"Worker {worker_id} claimed job {job.id}")
    await service.db.commit()

    await service.ensure_plan_and_steps(tenant_id, run_id)
    await service.lock_plan_on_start(tenant_id, run_id)

    while True:
        if job.cancel_requested:
            await _handle_cancel(service, job.id, tenant_id, run_id, reason="cancelled before step")
            await service.db.commit()
            return

        step = await service.repo.claim_next_step(tenant_id, run_id)
        if not step:
            steps = await service.repo.list_steps(tenant_id, run_id)
            if steps and all(s.status == "succeeded" for s in steps):
                await service.mark_job_succeeded(job.id)
                await service.repo.set_run_status(
                    tenant_id,
                    run_id,
                    status="succeeded",
                    finished_at=utc_now(),
                    last_error=None,
                )
                await service.append_event(tenant_id, run_id, "worker_completed", "Run completed")
            else:
                job.locked_at = None
                job.locked_by = None
                await service.db.flush()
            await service.db.commit()
            return

        if job.cancel_requested:
            await _handle_cancel(service, job.id, tenant_id, run_id, reason="cancelled during step")
            await service.db.commit()
            return

        await service.append_event(
            tenant_id,
            run_id,
            "step_started",
            f"Starting step {step.step_key}",
            meta_json={"step_id": str(step.id), "step_key": step.step_key},
        )

        try:
            if step.step_key == "external_llm_company_discovery":
                allow_fixture = bool(int(os.getenv("EXTERNAL_LLM_ENABLED", "0") or 0))
                summary = await service.process_llm_json_sources_for_run(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    allow_fixture=allow_fixture,
                )
                await service.repo.mark_step_succeeded(step.id, output_json=summary)
                await service.append_event(
                    tenant_id,
                    run_id,
                    "step_succeeded",
                    "Completed external_llm_company_discovery",
                    meta_json=summary,
                )
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "fetch_url_sources":
                extractor = CompanyExtractionService(service.db)
                result = await extractor.fetch_url_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )

                if result.get("retry_scheduled"):
                    backoff_seconds = result.get("retry_backoff_seconds") or min(300, 30 * max(1, step.attempt_count))
                    await service.repo.mark_step_failed(
                        step.id,
                        "pending_url_retries",
                        backoff_seconds=backoff_seconds,
                    )
                    await service.mark_job_failed(job.id, "pending_url_retries", backoff_seconds=backoff_seconds)
                    await service.append_event(
                        tenant_id,
                        run_id,
                        "step_failed",
                        f"Retrying step {step.step_key}",
                        meta_json={"step_key": step.step_key, "result": result},
                        status="failed",
                    )
                    await service.db.commit()
                    return

                if result.get("pending_recheck"):
                    step.status = "pending"
                    pending_next = result.get("pending_recheck_next_retry_at")
                    next_retry_at = None
                    if isinstance(pending_next, str):
                        try:
                            next_retry_at = datetime.fromisoformat(pending_next)
                        except ValueError:
                            next_retry_at = None
                    elif isinstance(pending_next, datetime):
                        next_retry_at = pending_next

                    backoff_seconds = 2
                    if next_retry_at:
                        delta_seconds = int((next_retry_at - utc_now()).total_seconds())
                        backoff_seconds = max(1, delta_seconds)
                    step.next_retry_at = next_retry_at or (utc_now() + timedelta(seconds=backoff_seconds))

                    await service.mark_job_failed(job.id, "pending_url_recheck", backoff_seconds=backoff_seconds)
                    await service.append_event(
                        tenant_id,
                        run_id,
                        "step_pending",
                        f"Revalidating step {step.step_key} with conditional fetch",
                        meta_json={
                            "step_key": step.step_key,
                            "result": result,
                            "next_retry_at": step.next_retry_at.isoformat() if step.next_retry_at else None,
                            "pending_recheck_backoff": backoff_seconds,
                        },
                        status="ok",
                    )
                    await service.db.flush()
                    await service.db.commit()
                    return

                await service.repo.mark_step_succeeded(step.id, output_json=result)
                await service.append_event(
                    tenant_id,
                    run_id,
                    "step_succeeded",
                    f"Completed step {step.step_key}",
                    meta_json={"step_key": step.step_key, "result": result},
                )
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "extract_url_sources":
                extractor = CompanySourceExtractionService(service.db)
                result = await extractor.extract_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
                await service.repo.mark_step_succeeded(step.id, output_json=result)
                await service.append_event(
                    tenant_id,
                    run_id,
                    "step_succeeded",
                    f"Completed step {step.step_key}",
                    meta_json={"step_key": step.step_key, "result": result},
                )
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "classify_sources":
                classifier = CompanySourceExtractionService(service.db)
                result = await classifier.classify_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
                await service.repo.mark_step_succeeded(step.id, output_json=result)
                await service.append_event(
                    tenant_id,
                    run_id,
                    "step_succeeded",
                    f"Completed step {step.step_key}",
                    meta_json={"step_key": step.step_key, "result": result},
                )
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "process_sources":
                extractor = CompanyExtractionService(service.db)
                result = await extractor.process_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
                await service.repo.mark_step_succeeded(step.id, output_json=result)
                await service.append_event(
                    tenant_id,
                    run_id,
                    "step_succeeded",
                    f"Completed step {step.step_key}",
                    meta_json={"step_key": step.step_key, "result": result},
                )
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "ingest_lists":
                summary = await service.ingest_list_sources(tenant_id, run_id)
                await service.repo.mark_step_succeeded(step.id, output_json=summary)
                await service.append_event(tenant_id, run_id, "step_succeeded", "Completed ingest_lists", meta_json=summary)
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "ingest_proposal":
                summary = await service.ingest_proposal_sources(tenant_id, run_id)
                await service.repo.mark_step_succeeded(step.id, output_json=summary)
                await service.append_event(tenant_id, run_id, "step_succeeded", "Completed ingest_proposal", meta_json=summary)
                await service.db.flush()
                await service.db.commit()
                continue

            if step.step_key == "finalize":
                steps_state = await service.repo.list_steps(tenant_id, run_id)
                blockers = [
                    s.step_key
                    for s in steps_state
                    if s.step_key != "finalize" and s.status not in {"succeeded", "skipped", "cancelled"}
                ]
                if blockers:
                    backoff_seconds = min(300, 30 * max(1, step.attempt_count))
                    await service.repo.mark_step_failed(
                        step.id,
                        "pending steps: " + ", ".join(blockers),
                        backoff_seconds=backoff_seconds,
                    )
                    await service.append_event(
                        tenant_id,
                        run_id,
                        "step_failed",
                        "Finalize blocked",
                        meta_json={"blockers": blockers},
                        status="failed",
                    )
                    await service.db.flush()
                    await service.db.commit()
                    return

                await service.repo.mark_step_succeeded(step.id, output_json={"completed": True})
                await service.mark_job_succeeded(job.id)
                await service.repo.set_run_status(
                    tenant_id,
                    run_id,
                    status="succeeded",
                    finished_at=utc_now(),
                    last_error=None,
                )
                await service.append_event(tenant_id, run_id, "worker_completed", "Run completed")
                await service.db.commit()
                return

            await service.repo.mark_step_failed(step.id, f"unknown_step:{step.step_key}")
            await service.mark_job_failed(job.id, f"unknown_step:{step.step_key}")
            await service.repo.set_run_status(
                tenant_id,
                run_id,
                status="failed",
                last_error=f"unknown_step:{step.step_key}",
            )
            await service.append_event(
                tenant_id,
                run_id,
                "step_failed",
                f"Unknown step {step.step_key}",
                status="failed",
            )
            await service.db.commit()
            return

        except Exception as exc:  # noqa: BLE001
            await service.db.rollback()
            backoff_seconds = min(300, 30 * max(1, step.attempt_count))
            message = str(exc)
            await service.repo.mark_step_failed(step.id, message, backoff_seconds=backoff_seconds)
            await service.mark_job_failed(job.id, message, backoff_seconds=backoff_seconds)
            await service.repo.set_run_status(
                tenant_id,
                run_id,
                status="failed",
                last_error=message,
            )
            await service.append_event(tenant_id, run_id, "step_failed", message, status="failed")
            await service.db.commit()
            return


async def run_worker(loop: bool, sleep_seconds: int) -> int:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        while True:
            job = await service.claim_next_job(worker_id)
            if not job:
                if not loop:
                    return 0
                await asyncio.sleep(sleep_seconds)
                continue

            await _process_job(service, job, worker_id)
            if not loop:
                return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Company research worker")
    parser.add_argument("--once", action="store_true", help="Process a single job and exit")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--sleep", type=int, default=2, help="Sleep seconds between polls when looping")
    args = parser.parse_args()

    loop_mode = args.loop and not args.once
    return asyncio.run(run_worker(loop=loop_mode, sleep_seconds=args.sleep))


if __name__ == "__main__":
    raise SystemExit(main())

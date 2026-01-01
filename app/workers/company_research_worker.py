"""Company research worker for queued run processing."""

import argparse
import asyncio
import os
import socket
from datetime import datetime
from typing import Optional

from app.db.session import get_async_session_context
from app.services.company_research_service import CompanyResearchService
from app.services.company_extraction_service import CompanyExtractionService


async def _handle_cancel(
    service: CompanyResearchService,
    job_id,
    tenant_id: str,
    run_id,
    reason: Optional[str] = None,
):
    run = await service.get_research_run(tenant_id, run_id)
    allow_status_update = run and run.status in {"queued", "running", "cancel_requested"}

    await service.mark_job_cancelled(job_id, last_error=reason)
    if allow_status_update:
        await service.repo.set_run_status(
            tenant_id,
            run_id,
            status="cancelled",
            last_error=reason,
            finished_at=datetime.utcnow(),
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

    # Move to running state
    job = await service.mark_job_running(job.id, worker_id)
    if not job:
        await service.append_event(tenant_id, run_id, "worker_failed", "Unable to mark job running", status="failed")
        await service.db.commit()
        return
    started_at = run.started_at or datetime.utcnow()
    await service.repo.set_run_status(
        tenant_id,
        run_id,
        status="running",
        last_error=None,
        started_at=started_at,
    )
    await service.append_event(tenant_id, run_id, "worker_claimed", f"Worker {worker_id} claimed job {job.id}")
    await service.db.commit()

    if job.cancel_requested:
        await _handle_cancel(service, job.id, tenant_id, run_id, reason="cancelled before start")
        await service.db.commit()
        return

    try:
        extractor = CompanyExtractionService(service.db)
        extraction_result = await extractor.process_sources(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        await service.append_event(
            tenant_id,
            run_id,
            "process_sources",
            f"Processed {extraction_result.get('processed', 0)} sources",
            meta_json=extraction_result,
        )

        if job.cancel_requested:
            await _handle_cancel(service, job.id, tenant_id, run_id, reason="cancelled after sources")
            await service.db.commit()
            return

        await service.mark_job_succeeded(job.id)
        await service.repo.set_run_status(
            tenant_id,
            run_id,
            status="succeeded",
            finished_at=datetime.utcnow(),
            last_error=None,
        )
        await service.append_event(tenant_id, run_id, "worker_completed", "Run completed")
        await service.db.commit()

    except Exception as exc:  # noqa: BLE001
        await service.db.rollback()
        backoff_seconds = min(300, 30 * (job.attempt_count + 1))
        message = str(exc)
        await service.mark_job_failed(job.id, message, backoff_seconds=backoff_seconds)
        await service.repo.set_run_status(
            tenant_id,
            run_id,
            status="failed",
            last_error=message,
        )
        await service.append_event(tenant_id, run_id, "worker_failed", message, status="failed")
        await service.db.commit()


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

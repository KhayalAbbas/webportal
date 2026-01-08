"""Phase 10.3 proof: cancel, retry, and stale lease recovery for acquire+extract jobs.

This proof runs fully offline against local fixtures and writes deterministic
artifacts under scripts/proofs/_artifacts.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("RUN_PROOFS_FIXTURES", "1")
os.environ.setdefault("PYTHONASYNCIODEBUG", "0")

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SEED_URLS_ARTIFACT = ARTIFACT_DIR / "phase_10_3_seed_urls.json"
ENQUEUE_CANCEL_ARTIFACT = ARTIFACT_DIR / "phase_10_3_enqueue_for_cancel.json"
CANCEL_ARTIFACT = ARTIFACT_DIR / "phase_10_3_cancel.json"
STATUS_CANCEL_ARTIFACT = ARTIFACT_DIR / "phase_10_3_status_cancelled.json"
ENQUEUE_FAIL_ARTIFACT = ARTIFACT_DIR / "phase_10_3_enqueue_fail.json"
STATUS_FAILED_ARTIFACT = ARTIFACT_DIR / "phase_10_3_status_failed.json"
RETRY_ARTIFACT = ARTIFACT_DIR / "phase_10_3_retry.json"
STATUS_RETRIED_ARTIFACT = ARTIFACT_DIR / "phase_10_3_status_retried_succeeded.json"
ENQUEUE_RECLAIM_ARTIFACT = ARTIFACT_DIR / "phase_10_3_enqueue_reclaim.json"
STATUS_RECLAIM_ARTIFACT = ARTIFACT_DIR / "phase_10_3_status_reclaimed.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_10_3_db_excerpt.txt"
PROOF_SUMMARY_ARTIFACT = ARTIFACT_DIR / "phase_10_3_proof.txt"
PROOF_CONSOLE_ARTIFACT = ARTIFACT_DIR / "phase_10_3_proof_console.txt"

TENANT_ID: UUID | None = None
RUN_ID: UUID | None = None
ROLE_ID: UUID | None = None

LOG_LINES: List[str] = []
ASSERTIONS: List[str] = []


class StubUser:
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"
        self.role = "admin"


def override_user() -> StubUser:
    if TENANT_ID is None:
        raise RuntimeError("tenant not initialized")
    return StubUser(TENANT_ID)


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)
    PROOF_CONSOLE_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE_ARTIFACT.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")


@contextmanager
def start_fixture_server(port: int = 8899):
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), FixtureHandler)
        base_url = f"http://127.0.0.1:{port}"
    except OSError:
        server = find_free_server("127.0.0.1")
        host, dyn_port = server.server_address
        base_url = f"http://{host}:{dyn_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, base_url
    finally:
        server.shutdown()


async def init_tenant_and_role() -> Tuple[UUID, UUID]:
    async with AsyncSessionLocal() as session:
        row = await session.execute(text("SELECT tenant_id, id FROM role ORDER BY tenant_id, id LIMIT 1"))
        record = row.first()
        if not record:
            raise RuntimeError("No role/tenant row available")
        return UUID(str(record.tenant_id)), UUID(str(record.id))


async def create_run(session, tenant_id: UUID, role_id: UUID) -> UUID:
    service = CompanyResearchService(session)
    run = await service.create_research_run(
        tenant_id=str(tenant_id),
        data=CompanyResearchRunCreate(
            role_mandate_id=role_id,
            name="phase_10_3_job_controls",
            description="Phase 10.3 cancel/retry/lease proof",
            sector="Testing",
            region_scope=["US"],
            status="active",
        ),
        created_by_user_id=None,
    )
    await session.commit()
    return UUID(str(run.id))


async def seed_urls(client: AsyncClient, run_id: UUID, base_url: str) -> List[Dict[str, Any]]:
    payloads = [
        {"title": "content_html", "url": f"{base_url}/content_html"},
        {"title": "thin_html", "url": f"{base_url}/thin_html"},
        {"title": "login_html", "url": f"{base_url}/login_html"},
    ]
    seeds: List[Dict[str, Any]] = []
    for body in payloads:
        resp = await client.post(f"/company-research/runs/{run_id}/sources/url", json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"seed url failed {resp.status_code}: {resp.text}")
        seeds.append(resp.json())
    write_json(SEED_URLS_ARTIFACT, seeds)
    log(f"Seeded {len(seeds)} URL sources for run {run_id}")
    return seeds


async def enqueue_job(client: AsyncClient, run_id: UUID, max_urls: int, force: bool, artifact: Path) -> Dict[str, Any]:
    payload = {"max_urls": max_urls, "force": force}
    resp = await client.post(f"/company-research/runs/{run_id}/acquire-extract:enqueue", json=payload)
    body = {"status": resp.status_code, "body": resp.json()}
    write_json(artifact, body)
    if resp.status_code != 200:
        raise RuntimeError(f"enqueue failed {resp.status_code}: {resp.text}")
    return body


async def job_status(client: AsyncClient, job_id: UUID, artifact: Optional[Path] = None) -> Dict[str, Any]:
    resp = await client.get(f"/company-research/jobs/{job_id}")
    body = resp.json()
    if artifact:
        write_json(artifact, body)
    return body


async def process_one_job(worker_id: str, *, stale_after_seconds: int = 1800, override_run=None) -> bool:
    async with AsyncSessionLocal() as session:
        service = CompanyResearchService(session)
        job = await service.claim_next_job(
            worker_id,
            job_type="acquire_extract_async",
            stale_after_seconds=stale_after_seconds,
        )
        if not job:
            return False
        if override_run:
            service.run_acquire_extract = override_run  # type: ignore
        try:
            await service.execute_acquire_extract_job(str(job.tenant_id), job.id, worker_id=worker_id)
        except Exception:
            # execute_acquire_extract_job already records failure; swallow for deterministic testing
            pass
        return True


async def force_stale_running(job_id: UUID, *, locked_by: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                update company_research_jobs
                set status = 'running', locked_at = now() - interval '2 hours', locked_by = :locked_by
                where id = :job_id
                """
            ),
            {"job_id": str(job_id), "locked_by": locked_by},
        )
        await session.commit()


async def record_db_excerpt(run_id: UUID, job_ids: List[UUID]) -> None:
    async with AsyncSessionLocal() as session:
        rows_jobs = await session.execute(
            text(
                """
                select id, status, job_type, attempt_count, max_attempts, params_hash, params_json,
                       progress_json, error_json, cancel_requested, locked_at, locked_by, started_at,
                       finished_at, next_retry_at, last_error, created_at, updated_at
                from company_research_jobs
                where run_id = :run_id and id = any(:job_ids)
                order by created_at
                """
            ),
            {"run_id": str(run_id), "job_ids": [str(j) for j in job_ids]},
        )
        rows_events = await session.execute(
            text(
                """
                select event_type, status, input_json, output_json, error_message, created_at
                from research_events
                where company_research_run_id = :run_id
                  and event_type like 'acquire_extract%'
                order by created_at
                """
            ),
            {"run_id": str(run_id)},
        )
        lines: List[str] = ["== company_research_jobs =="]
        for row in rows_jobs.mappings():
            lines.append(json.dumps(dict(row), default=str, sort_keys=True))
        lines.append("\n== research_events (acquire_extract*) ==")
        for row in rows_events.mappings():
            lines.append(json.dumps(dict(row), default=str, sort_keys=True))
        DB_EXCERPT_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
        log(
            f"DB excerpt jobs={rows_jobs.rowcount} events={rows_events.rowcount} for run {run_id}"
        )


def record_assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    ASSERTIONS.append(f"PASS: {message}")


async def main() -> None:
    global TENANT_ID, RUN_ID, ROLE_ID
    for path in [
        SEED_URLS_ARTIFACT,
        ENQUEUE_CANCEL_ARTIFACT,
        CANCEL_ARTIFACT,
        STATUS_CANCEL_ARTIFACT,
        ENQUEUE_FAIL_ARTIFACT,
        STATUS_FAILED_ARTIFACT,
        RETRY_ARTIFACT,
        STATUS_RETRIED_ARTIFACT,
        ENQUEUE_RECLAIM_ARTIFACT,
        STATUS_RECLAIM_ARTIFACT,
        DB_EXCERPT_ARTIFACT,
        PROOF_SUMMARY_ARTIFACT,
        PROOF_CONSOLE_ARTIFACT,
    ]:
        path.unlink(missing_ok=True)

    TENANT_ID, ROLE_ID = await init_tenant_and_role()
    app.dependency_overrides[verify_user_tenant_access] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"X-Tenant-ID": str(TENANT_ID)}
        client.headers.update(headers)

        async with AsyncSessionLocal() as session:
            RUN_ID = await create_run(session, TENANT_ID, ROLE_ID)
        log(f"run_id={RUN_ID} tenant_id={TENANT_ID}")

        with start_fixture_server() as (_, base_url):
            await seed_urls(client, RUN_ID, base_url)

            # Cancel while queued
            cancel_enq = await enqueue_job(client, RUN_ID, max_urls=3, force=False, artifact=ENQUEUE_CANCEL_ARTIFACT)
            cancel_job_id = UUID(cancel_enq["body"].get("job_id"))
            resp_cancel = await client.post(f"/company-research/jobs/{cancel_job_id}:cancel")
            write_json(CANCEL_ARTIFACT, {"status": resp_cancel.status_code, "body": resp_cancel.json()})
            await process_one_job("worker-cancel")  # should be no-op because status cancelled
            cancel_status = await job_status(client, cancel_job_id, STATUS_CANCEL_ARTIFACT)
            record_assert(cancel_status.get("status") == "cancelled", "cancelled job is terminal")
            record_assert(bool(cancel_status.get("finished_at")), "cancelled job has finished_at")

            # Retry flow
            fail_enq = await enqueue_job(client, RUN_ID, max_urls=2, force=True, artifact=ENQUEUE_FAIL_ARTIFACT)
            fail_job_id = UUID(fail_enq["body"].get("job_id"))

            async def _raise_failure(*_args, **_kwargs):
                raise RuntimeError("fixture_fail")

            await process_one_job("worker-fail", override_run=_raise_failure)
            failed_status = await job_status(client, fail_job_id, STATUS_FAILED_ARTIFACT)
            record_assert(failed_status.get("status") == "failed", "failed job recorded")
            record_assert(failed_status.get("error_json") is not None, "failed job has error_json")

            resp_retry = await client.post(f"/company-research/jobs/{fail_job_id}:retry", params={"reset_attempts": True})
            retry_body = {"status": resp_retry.status_code, "body": resp_retry.json()}
            write_json(RETRY_ARTIFACT, retry_body)
            record_assert(resp_retry.status_code == 200, "retry endpoint succeeded")
            retry_status = retry_body["body"]
            record_assert(retry_status.get("status") == "queued", "retry requeued job")

            await process_one_job("worker-retry")
            retried_status = await job_status(client, fail_job_id, STATUS_RETRIED_ARTIFACT)
            record_assert(retried_status.get("status") == "succeeded", "retried job succeeded")

            # Stale lease recovery
            reclaim_enq = await enqueue_job(client, RUN_ID, max_urls=1, force=True, artifact=ENQUEUE_RECLAIM_ARTIFACT)
            reclaim_job_id = UUID(reclaim_enq["body"].get("job_id"))
            await force_stale_running(reclaim_job_id, locked_by="stale-worker")
            await process_one_job("worker-reclaim", stale_after_seconds=1)
            reclaimed_status = await job_status(client, reclaim_job_id, STATUS_RECLAIM_ARTIFACT)
            record_assert(reclaimed_status.get("status") == "succeeded", "stale lease job reclaimed and succeeded")

        await record_db_excerpt(RUN_ID, [cancel_job_id, fail_job_id, reclaim_job_id])

    PROOF_SUMMARY_ARTIFACT.write_text(
        "\n".join(LOG_LINES + ["== assertions =="] + ASSERTIONS + ["PROOF_RESULT=PASS"]),
        encoding="utf-8",
    )
    log("Proof completed")


if __name__ == "__main__":
    asyncio.run(main())

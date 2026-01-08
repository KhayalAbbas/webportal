"""Phase 10.2 proof: acquire+extract worker concurrency.

Validates that two workers cannot double-run the same acquire_extract_async job:
- seeds fixture URLs
- enqueues one job
- starts two workers concurrently; only one claims and runs
- polls status to succeeded with progress_json
- re-enqueues same params to confirm idempotent reuse
Artifacts:
  phase_10_2_proof.txt
  phase_10_2_proof_console.txt
  phase_10_2_enqueue.json
  phase_10_2_worker1_log.txt
  phase_10_2_worker2_log.txt
  phase_10_2_status.json
  phase_10_2_db_excerpt.txt
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List, Tuple
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
from app.workers.acquire_extract_job_runner import AcquireExtractJobRunner  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

ENQUEUE_ARTIFACT = ARTIFACT_DIR / "phase_10_2_enqueue.json"
STATUS_ARTIFACT = ARTIFACT_DIR / "phase_10_2_status.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_10_2_db_excerpt.txt"
PROOF_SUMMARY_ARTIFACT = ARTIFACT_DIR / "phase_10_2_proof.txt"
PROOF_CONSOLE_ARTIFACT = ARTIFACT_DIR / "phase_10_2_proof_console.txt"
WORKER1_LOG = ARTIFACT_DIR / "phase_10_2_worker1_log.txt"
WORKER2_LOG = ARTIFACT_DIR / "phase_10_2_worker2_log.txt"

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
def start_fixture_server(port: int = 8897):
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
            name="phase_10_2_acquire_extract_worker",
            description="Phase 10.2 worker concurrency proof",
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
        {"title": "content_html_variant", "url": f"{base_url}/content_html_variant"},
        {"title": "thin_html", "url": f"{base_url}/thin_html"},
        {"title": "login_html", "url": f"{base_url}/login_html"},
    ]
    seeds: List[Dict[str, Any]] = []
    for body in payloads:
        resp = await client.post(f"/company-research/runs/{run_id}/sources/url", json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"seed url failed {resp.status_code}: {resp.text}")
        seeds.append(resp.json())
    log(f"Seeded {len(seeds)} URL sources for run {run_id}")
    return seeds


async def enqueue_job(
    client: AsyncClient,
    run_id: UUID,
    max_urls: int,
    force: bool,
    artifact: Path | None = None,
) -> Dict[str, Any]:
    payload = {"max_urls": max_urls, "force": force}
    resp = await client.post(f"/company-research/runs/{run_id}/acquire-extract:enqueue", json=payload)
    body = {"status": resp.status_code, "body": resp.json()}
    if artifact:
        write_json(artifact, body)
    if resp.status_code != 200:
        raise RuntimeError(f"enqueue failed {resp.status_code}: {resp.text}")
    return body


async def poll_job_status(client: AsyncClient, job_id: UUID, artifact: Path) -> Dict[str, Any]:
    for _ in range(30):
        resp = await client.get(f"/company-research/jobs/{job_id}")
        body = resp.json()
        write_json(artifact, body)
        status = body.get("status")
        if status in {"succeeded", "failed"}:
            return body
        await asyncio.sleep(0.2)
    raise RuntimeError("job did not reach terminal state in time")


def record_assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    ASSERTIONS.append(f"PASS: {message}")


async def db_excerpt(run_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        rows_jobs = await session.execute(
            text(
                """
                select id, tenant_id, run_id, job_type, status, params_hash, params_json, progress_json,
                       error_json, started_at, finished_at, attempt_count, max_attempts, created_at, updated_at
                from company_research_jobs
                where run_id = :run_id
                order by created_at
                """
            ),
            {"run_id": str(run_id)},
        )
        rows_events = await session.execute(
            text(
                """
                select event_type, status, input_json, output_json, error_message, created_at
                from research_events
                where company_research_run_id = :run_id and event_type like 'acquire_extract%'
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
            "DB excerpt rows_jobs=%s rows_events=%s"
            % (rows_jobs.rowcount, rows_events.rowcount)
        )


async def run_worker_once(runner: AcquireExtractJobRunner, log_path: Path) -> bool:
    log_path.write_text("", encoding="utf-8")
    try:
        log_path.write_text(f"worker_id={runner.worker_id}\nstarting=1\n", encoding="utf-8")
        processed = await runner.run_once()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"processed={processed}\n")
        return processed
    except Exception as exc:  # noqa: BLE001
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"error={exc}\n")
        raise


async def main() -> None:
    global TENANT_ID, RUN_ID, ROLE_ID
    for path in [
        ENQUEUE_ARTIFACT,
        STATUS_ARTIFACT,
        DB_EXCERPT_ARTIFACT,
        PROOF_SUMMARY_ARTIFACT,
        PROOF_CONSOLE_ARTIFACT,
        WORKER1_LOG,
        WORKER2_LOG,
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

            first_enqueue = await enqueue_job(client, RUN_ID, max_urls=4, force=False, artifact=None)
            first_job_id = UUID(str(first_enqueue["body"].get("job_id")))
            first_hash = first_enqueue["body"].get("params_hash")

            runner1 = AcquireExtractJobRunner(worker_id="worker1", poll_interval=0.1)
            runner2 = AcquireExtractJobRunner(worker_id="worker2", poll_interval=0.1)

            processed1, processed2 = await asyncio.gather(
                run_worker_once(runner1, WORKER1_LOG),
                run_worker_once(runner2, WORKER2_LOG),
            )

            record_assert(processed1 != processed2, "only one worker processes the job")
            processed_job = "worker1" if processed1 else "worker2"
            log(f"Job processed by {processed_job}")

            status_body = await poll_job_status(client, first_job_id, STATUS_ARTIFACT)
            record_assert(status_body.get("status") == "succeeded", "job succeeded via worker")
            touched = status_body.get("progress_json", {}).get("source_ids_touched", [])
            record_assert(len(touched) > 0, "progress_json includes touched sources")

            reused = await enqueue_job(client, RUN_ID, max_urls=4, force=False, artifact=None)
            record_assert(
                reused["body"].get("reused_reason") in {"duplicate_succeeded", "inflight"},
                "re-enqueue reuses succeeded job",
            )
            record_assert(reused["body"].get("params_hash") == first_hash, "re-enqueue params_hash unchanged")

            write_json(ENQUEUE_ARTIFACT, {"first": first_enqueue, "reuse": reused})

        await db_excerpt(RUN_ID)

    PROOF_SUMMARY_ARTIFACT.write_text(
        "\n".join(LOG_LINES + ["== assertions =="] + ASSERTIONS + ["PROOF_RESULT=PASS"]),
        encoding="utf-8",
    )
    log("Proof completed")


if __name__ == "__main__":
    asyncio.run(main())

"""Phase 10.1 proof: async acquire+extract job enqueue/status idempotency.

This proof runs the new async acquire+extract job flow:
- Seeds fixture-backed URL sources (no external network)
- Enqueues job with deterministic params and executes inline
- Polls status endpoint for terminal state
- Re-enqueues to confirm idempotent reuse
- Force=true enqueue creates a distinct params_hash/job and executes
- DB excerpt ties jobs, events, and touched source documents
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
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

ENQUEUE_FIRST_ARTIFACT = ARTIFACT_DIR / "phase_10_1_enqueue_first.json"
STATUS_FIRST_ARTIFACT = ARTIFACT_DIR / "phase_10_1_status_succeeded.json"
ENQUEUE_SECOND_ARTIFACT = ARTIFACT_DIR / "phase_10_1_enqueue_second.json"
ENQUEUE_FORCE_ARTIFACT = ARTIFACT_DIR / "phase_10_1_enqueue_force.json"
STATUS_FORCE_ARTIFACT = ARTIFACT_DIR / "phase_10_1_status_force.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_10_1_db_excerpt.txt"
PROOF_SUMMARY_ARTIFACT = ARTIFACT_DIR / "phase_10_1_proof.txt"
PROOF_CONSOLE_ARTIFACT = ARTIFACT_DIR / "phase_10_1_proof_console.txt"

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
            name="phase_10_1_async_acquire_extract",
            description="Phase 10.1 async acquire+extract job proof",
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
    write_json(ARTIFACT_DIR / "phase_10_1_seed_urls.json", seeds)
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


async def execute_job_inline(job_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = CompanyResearchService(session)
        await service.execute_acquire_extract_job(str(TENANT_ID), job_id)


async def poll_job_status(client: AsyncClient, job_id: UUID, artifact: Path) -> Dict[str, Any]:
    for _ in range(10):
        resp = await client.get(f"/company-research/jobs/{job_id}")
        body = resp.json()
        write_json(artifact, body)
        status = body.get("status")
        if status in {"succeeded", "failed"}:
            return body
        await asyncio.sleep(0.1)
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
        rows_sources = await session.execute(
            text(
                """
                select id, source_type, status, title, url, attempt_count, max_attempts, next_retry_at, fetched_at
                from source_documents
                where company_research_run_id = :run_id
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

        lines.append("\n== source_documents ==")
        for row in rows_sources.mappings():
            lines.append(json.dumps(dict(row), default=str, sort_keys=True))

        DB_EXCERPT_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
        log(f"DB excerpt rows_jobs={rows_jobs.rowcount} rows_events={rows_events.rowcount} rows_sources={rows_sources.rowcount}")


async def main() -> None:
    global TENANT_ID, RUN_ID, ROLE_ID
    for path in [
        ENQUEUE_FIRST_ARTIFACT,
        STATUS_FIRST_ARTIFACT,
        ENQUEUE_SECOND_ARTIFACT,
        ENQUEUE_FORCE_ARTIFACT,
        STATUS_FORCE_ARTIFACT,
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

            first_enqueue = await enqueue_job(client, RUN_ID, max_urls=4, force=False, artifact=ENQUEUE_FIRST_ARTIFACT)
            first_job_id = UUID(first_enqueue["body"].get("job_id"))
            first_hash = first_enqueue["body"].get("params_hash")

            await execute_job_inline(first_job_id)
            first_status = await poll_job_status(client, first_job_id, STATUS_FIRST_ARTIFACT)
            record_assert(first_status.get("status") == "succeeded", "first job succeeded")
            touched = first_status.get("progress_json", {}).get("source_ids_touched", [])
            record_assert(len(touched) > 0, "first job touched sources")

            second_enqueue = await enqueue_job(client, RUN_ID, max_urls=4, force=False, artifact=ENQUEUE_SECOND_ARTIFACT)
            record_assert(second_enqueue["body"].get("reused_reason") in {"duplicate_succeeded", "inflight"}, "second enqueue reused existing job")
            record_assert(second_enqueue["body"].get("params_hash") == first_hash, "second enqueue params_hash matches first")

            force_enqueue = await enqueue_job(client, RUN_ID, max_urls=4, force=True, artifact=ENQUEUE_FORCE_ARTIFACT)
            force_job_id = UUID(force_enqueue["body"].get("job_id"))
            force_hash = force_enqueue["body"].get("params_hash")
            record_assert(force_hash != first_hash, "force enqueue produced new params_hash")

            await execute_job_inline(force_job_id)
            force_status = await poll_job_status(client, force_job_id, STATUS_FORCE_ARTIFACT)
            record_assert(force_status.get("status") == "succeeded", "force job succeeded")

        await db_excerpt(RUN_ID)

    PROOF_SUMMARY_ARTIFACT.write_text(
        "\n".join(LOG_LINES + ["== assertions =="] + ASSERTIONS + ["PROOF_RESULT=PASS"]),
        encoding="utf-8",
    )
    log("Proof completed")


if __name__ == "__main__":
    asyncio.run(main())

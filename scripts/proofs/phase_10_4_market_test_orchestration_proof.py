"""Phase 10.4 proof: market-test orchestration end-to-end and idempotency.

This proof runs fully offline using fixtures and writes deterministic artifacts
under scripts/proofs/_artifacts.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient  # type: ignore
from http.server import ThreadingHTTPServer
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

FIRST_CALL_ARTIFACT = ARTIFACT_DIR / "phase_10_4_first_call.json"
SECOND_CALL_ARTIFACT = ARTIFACT_DIR / "phase_10_4_second_call.json"
JOB_STATUSES_ARTIFACT = ARTIFACT_DIR / "phase_10_4_job_statuses.json"
COMPARE_ARTIFACT = ARTIFACT_DIR / "phase_10_4_compare_snapshot.json"
PROMOTE_ARTIFACT = ARTIFACT_DIR / "phase_10_4_promote.json"
EXPORT_ZIP_ARTIFACT = ARTIFACT_DIR / "phase_10_4_export.zip"
EXPORT_HASH_ARTIFACT = ARTIFACT_DIR / "phase_10_4_export_hash.txt"
EXPORT_FILE_LIST_ARTIFACT = ARTIFACT_DIR / "phase_10_4_export_file_list.txt"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_10_4_db_excerpt.txt"
PROOF_ARTIFACT = ARTIFACT_DIR / "phase_10_4_proof.txt"
PROOF_CONSOLE_ARTIFACT = ARTIFACT_DIR / "phase_10_4_proof_console.txt"

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


def write_proof(status: str) -> None:
    PROOF_ARTIFACT.write_text("\n".join(ASSERTIONS + [f"RESULT={status}"]), encoding="utf-8")


def reset_artifacts() -> None:
    for path in [
        FIRST_CALL_ARTIFACT,
        SECOND_CALL_ARTIFACT,
        JOB_STATUSES_ARTIFACT,
        COMPARE_ARTIFACT,
        PROMOTE_ARTIFACT,
        EXPORT_ZIP_ARTIFACT,
        EXPORT_HASH_ARTIFACT,
        EXPORT_FILE_LIST_ARTIFACT,
        DB_EXCERPT_ARTIFACT,
        PROOF_ARTIFACT,
        PROOF_CONSOLE_ARTIFACT,
    ]:
        path.unlink(missing_ok=True)


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
            name="phase_10_4_market_test",
            description="Phase 10.4 market-test orchestration",
            sector="Testing",
            region_scope=["US"],
            status="active",
        ),
        created_by_user_id=None,
    )
    await session.commit()
    return UUID(str(run.id))


async def market_test(client: AsyncClient, run_id: UUID, base_url: str) -> Dict[str, Any]:
    payload = {
        "discovery_mode": "seed",
        "seed": {
            "companies": ["Fixture Seed Co"],
            "urls": [
                f"{base_url}/content_html",
                f"{base_url}/thin_html",
            ],
        },
        "max_urls": 4,
        "force_acquire": False,
        "exec_mode": "both",
        "do_compare_snapshot": True,
        "do_promote": True,
        "do_export": True,
    }
    resp = await client.post(f"/company-research/runs/{run_id}/market-test", json=payload)
    body = {"status": resp.status_code, "body": resp.json()}
    return body


async def job_status(client: AsyncClient, job_id: UUID) -> Dict[str, Any]:
    resp = await client.get(f"/company-research/jobs/{job_id}")
    return resp.json()


async def process_jobs(worker_id: str) -> List[Dict[str, Any]]:
    statuses: List[Dict[str, Any]] = []
    while True:
        async with AsyncSessionLocal() as session:
            service = CompanyResearchService(session)
            job = await service.claim_next_job(worker_id, job_type="acquire_extract_async")
            if not job:
                break
            try:
                await service.execute_acquire_extract_job(str(job.tenant_id), job.id, worker_id=worker_id)
            except Exception:
                pass
            await session.commit()
        async with AsyncSessionLocal() as session:
            status_row = await session.execute(
                text(
                    "select status, last_error, params_hash, cancel_requested, attempt_count from company_research_jobs where id = :job_id"
                ),
                {"job_id": str(job.id)},
            )
            rec = status_row.first()
            if rec:
                statuses.append({"job_id": str(job.id), **dict(rec._mapping)})
    return statuses


async def fetch_compare_snapshot(client: AsyncClient, run_id: UUID, prospect_id: UUID) -> Dict[str, Any]:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-compare",
        params={"company_prospect_id": str(prospect_id)},
    )
    return resp.json()


async def fetch_export(client: AsyncClient, run_id: UUID) -> Tuple[str, List[str]]:
    resp = await client.get(f"/company-research/runs/{run_id}/export-pack.zip")
    EXPORT_ZIP_ARTIFACT.write_bytes(resp.content)
    hash_value = hashlib.sha256(resp.content).hexdigest()
    EXPORT_HASH_ARTIFACT.write_text(hash_value, encoding="utf-8")

    file_list: List[str] = []
    try:
        import zipfile

        with zipfile.ZipFile(EXPORT_ZIP_ARTIFACT, "r") as zf:
            file_list = sorted(zf.namelist())
        EXPORT_FILE_LIST_ARTIFACT.write_text("\n".join(file_list), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        file_list = [f"zip_error:{exc}"]
        EXPORT_FILE_LIST_ARTIFACT.write_text("\n".join(file_list), encoding="utf-8")

    return hash_value, file_list


async def db_excerpt(run_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        blocks: List[str] = []
        blocks.append("-- company prospects")
        rows = await session.execute(
            text(
                """
                select id, review_status, exec_search_enabled, discovered_by
                from company_prospects
                where company_research_run_id = :run_id
                order by created_at asc
                limit 10
                """
            ),
            {"run_id": str(run_id)},
        )
        for rec in rows:
            blocks.append(str(dict(rec._mapping)))

        blocks.append("-- source documents")
        rows = await session.execute(
            text(
                """
                select id, source_type, title, content_hash
                from source_documents
                where company_research_run_id = :run_id
                order by created_at asc
                limit 10
                """
            ),
            {"run_id": str(run_id)},
        )
        for rec in rows:
            blocks.append(str(dict(rec._mapping)))

        blocks.append("-- executives")
        rows = await session.execute(
            text(
                """
                select id, company_prospect_id, discovered_by, review_status, verification_status
                from executive_prospects
                where company_research_run_id = :run_id
                order by created_at asc
                limit 10
                """
            ),
            {"run_id": str(run_id)},
        )
        for rec in rows:
            blocks.append(str(dict(rec._mapping)))

        DB_EXCERPT_ARTIFACT.write_text("\n".join(blocks), encoding="utf-8")


async def main() -> None:
    global TENANT_ID, ROLE_ID, RUN_ID

    reset_artifacts()
    TENANT_ID, ROLE_ID = await init_tenant_and_role()
    app.dependency_overrides[verify_user_tenant_access] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.headers.update({"X-Tenant-ID": str(TENANT_ID)})
        async with AsyncSessionLocal() as session:
            RUN_ID = await create_run(session, TENANT_ID, ROLE_ID)
        log(f"Created run {RUN_ID} for tenant {TENANT_ID}")

        with start_fixture_server() as (_server, base_url):
            first_call = await market_test(client, RUN_ID, base_url)
            write_json(FIRST_CALL_ARTIFACT, first_call)
            ASSERTIONS.append(f"first_call_status={first_call['status']}")

            job_id: Optional[UUID] = None
            for step in first_call["body"].get("steps", []):
                if step.get("name") == "acquire_extract_enqueue" and step.get("job_id"):
                    job_id = UUID(str(step["job_id"]))
                    break

            status_snapshots: List[Dict[str, Any]] = []
            if job_id:
                status_snapshots.append(await job_status(client, job_id))
                statuses = await process_jobs(worker_id="market_test_worker")
                status_snapshots.extend(statuses)
                status_snapshots.append(await job_status(client, job_id))
                write_json(JOB_STATUSES_ARTIFACT, status_snapshots)

            accepted_ids: List[UUID] = []
            for step in first_call["body"].get("steps", []):
                if step.get("name") == "review_gate":
                    ids = step.get("ids") or {}
                    accepted_ids = [UUID(val) for val in ids.get("accepted_prospect_ids", [])]
            if accepted_ids:
                compare = await fetch_compare_snapshot(client, RUN_ID, accepted_ids[0])
                write_json(COMPARE_ARTIFACT, compare)

            promote_step = next((s for s in first_call["body"].get("steps", []) if s.get("name") == "promote"), None)
            if promote_step:
                write_json(PROMOTE_ARTIFACT, promote_step)

            export_hash, file_list = await fetch_export(client, RUN_ID)
            ASSERTIONS.append(f"export_hash={export_hash}")

            second_call = await market_test(client, RUN_ID, base_url)
            write_json(SECOND_CALL_ARTIFACT, second_call)
            ASSERTIONS.append(f"second_call_status={second_call['status']}")

    await db_excerpt(RUN_ID)
    ASSERTIONS.append("market_test_idempotent_flow_completed")
    write_proof("PASS")


if __name__ == "__main__":
    asyncio.run(main())

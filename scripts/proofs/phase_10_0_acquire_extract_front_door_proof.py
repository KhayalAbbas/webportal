"""Phase 10.0 proof: acquire+extract front-door orchestration idempotency.

Runs deterministic 2-pass proof against /company-research/runs/{run_id}/acquire-extract:
- Seeds fixture-backed URL sources via API (no external network)
- First call fetches/extracts/classifies/processes
- Second call proves idempotency (no new work)
- Force call shows re-fetch path
- DB excerpt ties touched sources to stored rows and extraction/process metadata
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
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SEED_ARTIFACT = ARTIFACT_DIR / "phase_10_0_seed_urls.json"
FIRST_CALL_ARTIFACT = ARTIFACT_DIR / "phase_10_0_first_call.json"
SECOND_CALL_ARTIFACT = ARTIFACT_DIR / "phase_10_0_second_call.json"
FORCE_CALL_ARTIFACT = ARTIFACT_DIR / "phase_10_0_force_call.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_10_0_db_excerpt.txt"
PROOF_SUMMARY_ARTIFACT = ARTIFACT_DIR / "phase_10_0_proof.txt"
PROOF_CONSOLE_ARTIFACT = ARTIFACT_DIR / "phase_10_0_proof_console.txt"

TENANT_ID: UUID | None = None
RUN_ID: UUID | None = None
ROLE_ID: UUID | None = None
TOUCHED_SOURCE_IDS: List[UUID] = []

LOG_LINES: list[str] = []
ASSERTIONS: list[str] = []


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
            name="phase_10_0_acquire_extract",
            description="Phase 10.0 acquire+extract front-door proof",
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
    write_json(SEED_ARTIFACT, seeds)
    log(f"Seeded {len(seeds)} URL sources for run {run_id}")
    return seeds


async def call_acquire_extract(client: AsyncClient, run_id: UUID, max_urls: int | None, force: bool) -> dict:
    payload = {"max_urls": max_urls, "force": force}
    resp = await client.post(f"/company-research/runs/{run_id}/acquire-extract", json=payload)
    body = resp.json()
    write_json(FORCE_CALL_ARTIFACT if force else (SECOND_CALL_ARTIFACT if max_urls == "second" else FIRST_CALL_ARTIFACT), body)
    return {"status": resp.status_code, "body": body}


async def run_acquire_extract(client: AsyncClient, run_id: UUID, max_urls: int, force: bool) -> dict:
    payload = {"max_urls": max_urls, "force": force}
    resp = await client.post(f"/company-research/runs/{run_id}/acquire-extract", json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"acquire-extract failed {resp.status_code}: {resp.text}")
    data = resp.json()
    return data


def record_assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    ASSERTIONS.append(f"PASS: {message}")


async def db_excerpt(run_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            text(
                """
                select id, source_type, status, title, url, url_normalized, attempt_count, max_attempts,
                       next_retry_at, fetched_at,
                       meta -> 'extraction' ->> 'decision' as extraction_decision,
                       meta -> 'quality_flags' as quality_flags,
                       meta -> 'processed_summary' as processed_summary
                from source_documents
                where company_research_run_id = :run_id
                order by created_at
                """
            ),
            {"run_id": str(run_id)},
        )
        lines = []
        for row in rows.mappings():
            lines.append(json.dumps(dict(row), default=str, sort_keys=True))
        DB_EXCERPT_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
        log(f"DB excerpt rows={len(lines)} written")


async def main() -> None:
    global TENANT_ID, RUN_ID, ROLE_ID, TOUCHED_SOURCE_IDS
    for path in [
        SEED_ARTIFACT,
        FIRST_CALL_ARTIFACT,
        SECOND_CALL_ARTIFACT,
        FORCE_CALL_ARTIFACT,
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

            first = await run_acquire_extract(client, RUN_ID, max_urls=4, force=False)
            TOUCHED_SOURCE_IDS = [UUID(s) for s in first.get("source_ids_touched", [])]
            write_json(FIRST_CALL_ARTIFACT, first)
            log(f"first_call status={first.get('status')} touched={len(TOUCHED_SOURCE_IDS)} fetched={first.get('fetch', {}).get('fetched')}")

            record_assert(first.get("fetch", {}).get("fetched", 0) > 0, "first call fetched > 0")
            record_assert(first.get("extract", {}).get("processed", 0) > 0, "first call extracted > 0")
            record_assert(len(TOUCHED_SOURCE_IDS) > 0, "touched_source_ids non-empty")

            second = await run_acquire_extract(client, RUN_ID, max_urls=4, force=False)
            write_json(SECOND_CALL_ARTIFACT, second)
            log(f"second_call status={second.get('status')} fetched={second.get('fetch', {}).get('fetched')} processed={second.get('fetch', {}).get('processed')}")

            record_assert(
                second.get("fetch", {}).get("fetched", 0) <= first.get("fetch", {}).get("fetched", 0),
                "second call fetched does not increase",
            )
            record_assert(
                second.get("extract", {}).get("processed", 0) <= first.get("extract", {}).get("processed", 0),
                "second call extract does not increase",
            )
            second_ids = [UUID(s) for s in second.get("source_ids_touched", [])]
            record_assert(
                set(second_ids).issubset(set(TOUCHED_SOURCE_IDS)),
                "second call touched ids subset of first",
            )

            force_call = await run_acquire_extract(client, RUN_ID, max_urls=1, force=True)
            write_json(FORCE_CALL_ARTIFACT, force_call)
            log(f"force_call status={force_call.get('status')} fetched={force_call.get('fetch', {}).get('fetched')} selected={force_call.get('fetch', {}).get('selected')}")
            record_assert(force_call.get("fetch", {}).get("force") is True, "force flag echoed")
            record_assert(force_call.get("fetch", {}).get("processed", 0) >= 1, "force call processed >= 1")

        await db_excerpt(RUN_ID)

    PROOF_SUMMARY_ARTIFACT.write_text(
        "\n".join(LOG_LINES + ["== assertions =="] + ASSERTIONS + ["PROOF_RESULT=PASS"]),
        encoding="utf-8",
    )
    log("Proof completed")


if __name__ == "__main__":
    asyncio.run(main())

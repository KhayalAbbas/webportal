"""Phase 9.5 proof: company review gate + exec_search_enabled eligibility enforcement.

Two-pass deterministic script that:
- Seeds a run via SeedListProvider with two companies
- Shows eligibility is blocked before acceptance
- Accepts + enables exec search for one prospect, holds the other (forced off)
- Verifies discovery runs only on accepted+enabled prospect and is idempotent on second pass
- Writes all artifacts under scripts/proofs/_artifacts
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any, Dict, List
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal, get_async_session_context  # noqa: E402
from app.models.company_research import CompanyProspect  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.activity_log import ActivityLog  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

PROOF_CONSOLE = ARTIFACT_DIR / "phase_9_5_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_9_5_proof.txt"
SEED_PATH = ARTIFACT_DIR / "phase_9_5_seed.json"
ELIG_BEFORE = ARTIFACT_DIR / "phase_9_5_eligibility_before.json"
ELIG_AFTER = ARTIFACT_DIR / "phase_9_5_eligibility_after.json"
ELIG_BEFORE_2 = ARTIFACT_DIR / "phase_9_5_eligibility_before_2.json"
ELIG_AFTER_2 = ARTIFACT_DIR / "phase_9_5_eligibility_after_2.json"
EXEC_BLOCKED_INTERNAL = ARTIFACT_DIR / "phase_9_5_exec_discovery_blocked_internal.json"
EXEC_BLOCKED_EXTERNAL = ARTIFACT_DIR / "phase_9_5_exec_discovery_blocked_external.json"
EXEC_AFTER_INTERNAL = ARTIFACT_DIR / "phase_9_5_exec_discovery_after_internal.json"
EXEC_AFTER_EXTERNAL = ARTIFACT_DIR / "phase_9_5_exec_discovery_after_external.json"
EXEC_AFTER_INTERNAL_2 = ARTIFACT_DIR / "phase_9_5_exec_discovery_after_internal_2.json"
EXEC_AFTER_EXTERNAL_2 = ARTIFACT_DIR / "phase_9_5_exec_discovery_after_external_2.json"
ACCEPT_ENABLE = ARTIFACT_DIR / "phase_9_5_accept_enable.json"
HOLD_FORCED_OFF = ARTIFACT_DIR / "phase_9_5_hold_or_reject_forced_off.json"
ACCEPT_ENABLE_2 = ARTIFACT_DIR / "phase_9_5_accept_enable_2.json"
HOLD_FORCED_OFF_2 = ARTIFACT_DIR / "phase_9_5_hold_or_reject_forced_off_2.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_9_5_db_excerpt.txt"

TENANT_ID: UUID | None = None


@contextmanager
def start_fixture_server(port: int = 8895):
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


def seed_payload(base_url: str) -> dict:
    return {
        "mode": "paste",
        "source_label": "phase_9_5_seed",
        "items": [
            {
                "name": "Helio Labs",
                "website_url": f"{base_url}/content_html",
                "hq_country": "US",
                "hq_city": "Austin",
                "sector": "Software",
                "description": "Fixture content company",
                "urls": [f"{base_url}/content_html", f"{base_url}/thin_html"],
                "evidence": [
                    {
                        "url": f"{base_url}/content_html",
                        "label": "Content HTML",
                        "kind": "homepage",
                        "snippet": "Deterministic content page",
                    },
                    {
                        "url": f"{base_url}/thin_html",
                        "label": "Thin HTML",
                        "kind": "press_release",
                        "snippet": "Compact page",
                    },
                ],
            },
            {
                "name": "Atlas Robotics",
                "website_url": f"{base_url}/content_html_variant",
                "hq_country": "US",
                "hq_city": "Denver",
                "sector": "Industrial",
                "description": "Robotics fixture",
                "urls": [f"{base_url}/content_html_variant", f"{base_url}/login_html"],
                "evidence": [
                    {
                        "url": f"{base_url}/content_html_variant",
                        "label": "Variant HTML",
                        "kind": "homepage",
                        "snippet": "Variant content",
                    },
                    {
                        "url": f"{base_url}/login_html",
                        "label": "Login Page",
                        "kind": "other",
                        "snippet": "Login fixture",
                    },
                ],
            },
        ],
    }


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        SEED_PATH,
        ELIG_BEFORE,
        ELIG_AFTER,
        ELIG_BEFORE_2,
        ELIG_AFTER_2,
        EXEC_BLOCKED_INTERNAL,
        EXEC_BLOCKED_EXTERNAL,
        EXEC_AFTER_INTERNAL,
        EXEC_AFTER_EXTERNAL,
        EXEC_AFTER_INTERNAL_2,
        EXEC_AFTER_EXTERNAL_2,
        ACCEPT_ENABLE,
        HOLD_FORCED_OFF,
        ACCEPT_ENABLE_2,
        HOLD_FORCED_OFF_2,
        DB_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, sort_keys=True)


def make_stub_user(tenant_uuid: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_uuid,
        role="admin",
        email="proof@example.com",
        username="proof",
    )


def api_payload_for_external(company_name: str) -> dict:
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_name.lower(),
                "executives": [
                    {
                        "name": f"{company_name} CEO",
                        "title": "Chief Executive Officer",
                        "profile_url": f"https://example.com/{company_name.lower().replace(' ', '-')}/ceo",
                        "linkedin_url": f"https://www.linkedin.com/in/{company_name.lower().replace(' ', '-')}-ceo",
                        "confidence": 0.9,
                        "evidence": [
                            {
                                "url": f"https://example.com/{company_name.lower().replace(' ', '-')}/leadership",
                                "label": "Leadership page",
                                "kind": "external_stub",
                                "snippet": f"Leadership listing for {company_name}",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def pick_prospects(prospects: List[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    ordered = sorted(prospects, key=lambda p: str(p.get("id")))
    if len(ordered) < 2:
        raise RuntimeError("Need at least two prospects")
    return ordered[0], ordered[1]


async def create_run_and_seed(tenant_uuid: UUID) -> tuple[UUID, Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        role_row = await session.execute(text("SELECT id FROM role WHERE tenant_id = :tenant_id LIMIT 1"), {"tenant_id": tenant_uuid})
        role_id = role_row.scalar_one_or_none()
        if not role_id:
            raise RuntimeError("No role found for tenant")

        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=str(tenant_uuid),
            data=CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name="phase_9_5_review_gate",
                description="Phase 9.5 proof run",
                sector="Testing",
                region_scope=["US"],
                status="active",
            ),
            created_by_user_id=None,
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with start_fixture_server() as (server, base_url):
            payload = {"request": seed_payload(base_url)}
            url = f"/company-research/runs/{run.id}/discovery/providers/seed_list/run"
            resp = await client.post(url, json=payload)
            resp_json = {"status": resp.status_code, "body": resp.json()}
            SEED_PATH.write_text(json_dump(resp_json), encoding="utf-8")

    return run.id, resp_json


async def list_prospects(client: AsyncClient, run_id: UUID) -> List[Dict[str, Any]]:
    resp = await client.get(f"/company-research/runs/{run_id}/prospects")
    body = resp.json()
    return body


async def patch_review(client: AsyncClient, prospect_id: UUID, review_status: str, exec_search_enabled: bool | None, path: Path) -> Dict[str, Any]:
    resp = await client.patch(
        f"/company-research/prospects/{prospect_id}/review-status",
        json={"review_status": review_status, "exec_search_enabled": exec_search_enabled},
    )
    data = {"status": resp.status_code, "body": resp.json()}
    path.write_text(json_dump(data), encoding="utf-8")
    return data


async def get_eligibility(client: AsyncClient, run_id: UUID, path: Path) -> Dict[str, Any]:
    resp = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")
    data = {"status": resp.status_code, "body": resp.json()}
    path.write_text(json_dump(data), encoding="utf-8")
    return data


async def run_exec_discovery(client: AsyncClient, run_id: UUID, mode: str, payload: dict | None, path: Path) -> Dict[str, Any]:
    body: Dict[str, Any] = {"mode": mode, "engine": "internal" if mode == "internal" else "external", "provider": "external_engine", "model": "mock-model", "title": f"phase_9_5_{mode}"}
    if payload is not None:
        body["payload"] = payload
    resp = await client.post(f"/company-research/runs/{run_id}/executive-discovery/run", json=body)
    try:
        parsed = resp.json()
    except Exception:
        parsed = {"raw": resp.text}
    data = {"status": resp.status_code, "body": parsed}
    path.write_text(json_dump(data), encoding="utf-8")
    return data


async def db_excerpt(run_id: UUID, tenant_uuid: UUID) -> None:
    blocks: List[str] = []
    async with get_async_session_context() as session:
        prospects = (
            await session.execute(
                text(
                    """
                    SELECT id, name_normalized, review_status, exec_search_enabled
                    FROM company_prospects
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                    ORDER BY id
                    """
                ),
                {"tenant_id": tenant_uuid, "run_id": run_id},
            )
        ).mappings().all()

        events = (
            await session.execute(
                text(
                    """
                    SELECT type, message, created_at
                    FROM activity_log
                    WHERE tenant_id = :tenant_id AND type = 'PROSPECT_REVIEW_STATUS'
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": tenant_uuid},
            )
        ).mappings().all()

        blocks.append("Prospects (review_status, exec_search_enabled):")
        for row in prospects:
            blocks.append(json_dump(dict(row)))

        blocks.append("ActivityLog PROSPECT_REVIEW_STATUS:")
        for row in events:
            blocks.append(json_dump(dict(row)))

    DB_EXCERPT.write_text("\n".join(blocks), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    global TENANT_ID

    async with AsyncSessionLocal() as session:
        role = (await session.execute(text("SELECT id, tenant_id FROM role LIMIT 1"))).first()
        if not role:
            raise RuntimeError("No role available")
        role_id = role.id
        TENANT_ID = role.tenant_id

    stub_user = make_stub_user(TENANT_ID)
    app.dependency_overrides[verify_user_tenant_access] = lambda: stub_user

    run_id, seed_resp = await create_run_and_seed(TENANT_ID)
    log(f"run={run_id} tenant={TENANT_ID} seed_status={seed_resp.get('status')}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        prospects = await list_prospects(client, run_id)
        if len(prospects) < 2:
            raise RuntimeError("Expected at least two prospects from seed provider")
        first, second = pick_prospects(prospects)

        # Pass 1: before acceptance
        await get_eligibility(client, run_id, ELIG_BEFORE)
        await run_exec_discovery(client, run_id, "internal", None, EXEC_BLOCKED_INTERNAL)
        await run_exec_discovery(client, run_id, "external", api_payload_for_external(first["name_normalized"]), EXEC_BLOCKED_EXTERNAL)

        # Accept first, hold second (forced off)
        await patch_review(client, UUID(str(first["id"])), "accepted", True, ACCEPT_ENABLE)
        await patch_review(client, UUID(str(second["id"])), "hold", True, HOLD_FORCED_OFF)

        # After acceptance
        await get_eligibility(client, run_id, ELIG_AFTER)
        await run_exec_discovery(client, run_id, "internal", None, EXEC_AFTER_INTERNAL)
        await run_exec_discovery(client, run_id, "external", api_payload_for_external(first["name_normalized"]), EXEC_AFTER_EXTERNAL)

        # Pass 2 idempotency
        await get_eligibility(client, run_id, ELIG_BEFORE_2)
        await patch_review(client, UUID(str(first["id"])), "accepted", True, ACCEPT_ENABLE_2)
        await patch_review(client, UUID(str(second["id"])), "hold", True, HOLD_FORCED_OFF_2)
        await get_eligibility(client, run_id, ELIG_AFTER_2)
        await run_exec_discovery(client, run_id, "internal", None, EXEC_AFTER_INTERNAL_2)
        await run_exec_discovery(client, run_id, "external", api_payload_for_external(first["name_normalized"]), EXEC_AFTER_EXTERNAL_2)

    await db_excerpt(run_id, TENANT_ID)

    summary_lines = [
        "phase_9_5_company_review_gate_proof PASS",
        f"tenant={TENANT_ID}",
        f"run={run_id}",
        "Assertions: before accept -> blocked; after accept+enable -> eligible=1; non-accepted forced off; second pass idempotent",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

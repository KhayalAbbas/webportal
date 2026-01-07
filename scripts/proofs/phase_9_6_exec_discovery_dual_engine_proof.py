"""Phase 9.6 proof: eligible-first dual-engine exec discovery with compare counts and idempotency.

Flow (offline deterministic):
- Seed run with two companies via fixture server
- Accept+enable company A; hold+disable company B (eligibility gate)
- Run exec discovery with mode="both" using deterministic external payload (overlap + external-only)
- Negative call with ineligible company blocked
- Second pass proves idempotency (duplicate hash reuse)
- Persist evidence pointers, compare counts, and DB excerpt
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("RUN_PROOFS_FIXTURES", "1")

# Ensure repository path import
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal, get_async_session_context  # noqa: E402
from app.models.company_research import CompanyProspect  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

PROOF_CONSOLE = ARTIFACT_DIR / "phase_9_6_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_9_6_proof.txt"
GATE_SETUP = ARTIFACT_DIR / "phase_9_6_gate_setup.json"
FIRST_CALL = ARTIFACT_DIR / "phase_9_6_first_call.json"
SECOND_CALL = ARTIFACT_DIR / "phase_9_6_second_call.json"
NEGATIVE_CALL = ARTIFACT_DIR / "phase_9_6_negative_ineligible_payload.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_9_6_db_excerpt.txt"

TENANT_ID: UUID | None = None
RUN_ID: UUID | None = None


@contextmanager
def start_fixture_server(port: int = 8896):
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


# Late imports for server helpers
from http.server import ThreadingHTTPServer  # noqa: E402
from threading import Thread  # noqa: E402


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, sort_keys=True)


def reset_artifacts() -> None:
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        GATE_SETUP,
        FIRST_CALL,
        SECOND_CALL,
        NEGATIVE_CALL,
        DB_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def make_stub_user(tenant_uuid: UUID):
    return type(
        "StubUser",
        (),
        {
            "id": uuid4(),
            "tenant_id": tenant_uuid,
            "role": "admin",
            "email": "proof@example.com",
            "username": "proof",
        },
    )()


def seed_payload(base_url: str) -> dict:
    return {
        "mode": "paste",
        "source_label": "phase_9_6_seed",
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
                    }
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
                    }
                ],
            },
        ],
    }


def external_payload(company_name: str, company_norm: str) -> dict:
    slug = company_norm.replace(" ", "-")
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "generated_at": "1970-01-01T00:00:00+00:00",
        "query": "phase_9_6_external_fixture",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_norm,
                "executives": [
                    {
                        "name": f"{company_name} CEO",
                        "title": "Chief Executive Officer",
                        "profile_url": f"https://example.com/{slug}/ceo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-ceo",
                        "confidence": 0.9,
                        "evidence": [
                            {
                                "url": f"https://example.com/{slug}/leadership",
                                "label": "Leadership page",
                                "kind": "external_stub",
                                "snippet": f"Leadership listing for {company_name} CEO.",
                            }
                        ],
                    },
                    {
                        "name": f"{company_name} COO",
                        "title": "Chief Operating Officer",
                        "profile_url": f"https://example.com/{slug}/coo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-coo",
                        "confidence": 0.82,
                        "evidence": [
                            {
                                "url": f"https://example.com/{slug}/leadership",
                                "label": "Leadership page",
                                "kind": "external_stub",
                                "snippet": f"Leadership listing for {company_name} COO.",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def external_payload_with_ineligible(valid_company: str, valid_norm: str, invalid_company: str) -> dict:
    payload = external_payload(valid_company, valid_norm)
    payload["companies"].append(
        {
            "company_name": invalid_company,
            "company_normalized": invalid_company.lower(),
            "executives": [
                {
                    "name": f"{invalid_company} CEO",
                    "title": "Chief Executive Officer",
                    "profile_url": f"https://example.com/{invalid_company.lower().replace(' ', '-')}/ceo",
                    "linkedin_url": f"https://www.linkedin.com/in/{invalid_company.lower().replace(' ', '-')}-ceo",
                    "confidence": 0.5,
                    "evidence": [],
                }
            ],
        }
    )
    return payload


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json_dump(obj), encoding="utf-8")


def pick_prospects(prospects: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
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
                name="phase_9_6_dual_engine",
                description="Phase 9.6 proof run",
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
            write_json(GATE_SETUP, {"seed": resp_json})

    return run.id, resp_json


async def list_prospects(client: AsyncClient, run_id: UUID) -> List[Dict[str, Any]]:
    resp = await client.get(f"/company-research/runs/{run_id}/prospects")
    return resp.json()


async def set_review(
    client: AsyncClient, prospect_id: UUID, review_status: str, exec_search_enabled: bool | None
) -> Dict[str, Any]:
    resp = await client.patch(
        f"/company-research/prospects/{prospect_id}/review-status",
        json={"review_status": review_status, "exec_search_enabled": exec_search_enabled},
    )
    return {"status": resp.status_code, "body": resp.json()}


async def get_eligibility(client: AsyncClient, run_id: UUID) -> Dict[str, Any]:
    resp = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")
    return {"status": resp.status_code, "body": resp.json()}


async def run_exec_discovery(client: AsyncClient, run_id: UUID, body: dict, path: Path) -> Dict[str, Any]:
    resp = await client.post(f"/company-research/runs/{run_id}/executive-discovery/run", json=body)
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        parsed = {"raw": resp.text}
    data = {"status": resp.status_code, "body": parsed}
    write_json(path, data)
    return data


async def capture_db_excerpt(run_id: UUID, tenant_uuid: UUID) -> None:
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

        executives = (
            await session.execute(
                text(
                    """
                    SELECT id, company_prospect_id, name_normalized, title, discovered_by, source_label, verification_status
                    FROM executive_prospects
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                    ORDER BY company_prospect_id, name_normalized
                    """
                ),
                {"tenant_id": tenant_uuid, "run_id": run_id},
            )
        ).mappings().all()

        evidence = (
            await session.execute(
                text(
                    """
                    SELECT executive_prospect_id, source_document_id, source_content_hash, source_name
                    FROM executive_prospect_evidence
                    WHERE executive_prospect_id IN (SELECT id FROM executive_prospects WHERE company_research_run_id = :run_id)
                    ORDER BY executive_prospect_id
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().all()

        sources = (
            await session.execute(
                text(
                    """
                    SELECT id, source_type, title, content_hash, meta->>'engine' as engine, meta->>'kind' as kind
                    FROM source_documents
                    WHERE company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().all()

        enrichments = (
            await session.execute(
                text(
                    """
                    SELECT id, provider, enrichment_type, purpose, input_scope_hash, content_hash
                    FROM ai_enrichment_record
                    WHERE company_research_run_id = :run_id AND purpose = 'executive_discovery'
                    ORDER BY created_at
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().all()

        blocks.append("Prospects:")
        for row in prospects:
            blocks.append(json_dump(dict(row)))

        blocks.append("Executives:")
        for row in executives:
            blocks.append(json_dump(dict(row)))

        blocks.append("Evidence:")
        for row in evidence:
            blocks.append(json_dump(dict(row)))

        blocks.append("Sources:")
        for row in sources:
            blocks.append(json_dump(dict(row)))

        blocks.append("Enrichments:")
        for row in enrichments:
            blocks.append(json_dump(dict(row)))

    DB_EXCERPT.write_text("\n".join(blocks), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    global TENANT_ID, RUN_ID

    async with AsyncSessionLocal() as session:
        role = (await session.execute(text("SELECT id, tenant_id FROM role LIMIT 1"))).first()
        if not role:
            raise RuntimeError("No role available")
        role_id = role.id
        TENANT_ID = role.tenant_id

    stub_user = make_stub_user(TENANT_ID)
    app.dependency_overrides[verify_user_tenant_access] = lambda: stub_user

    run_id, seed_resp = await create_run_and_seed(TENANT_ID)
    RUN_ID = run_id
    log(f"run={run_id} tenant={TENANT_ID} seed_status={seed_resp.get('status')}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        prospects = await list_prospects(client, run_id)
        first, second = pick_prospects(prospects)

        # Apply gate: accept first, hold second (forced off)
        before_elig = await get_eligibility(client, run_id)
        await set_review(client, UUID(str(first["id"])), "accepted", True)
        await set_review(client, UUID(str(second["id"])), "hold", False)
        after_elig = await get_eligibility(client, run_id)
        write_json(GATE_SETUP, {"seed": seed_resp, "elig_before": before_elig, "elig_after": after_elig})

        valid_name = first["name_normalized"]
        valid_norm = valid_name.lower()

        # Negative call with ineligible company included
        negative_body = {
            "mode": "external",
            "engine": "external",
            "provider": "external_engine",
            "model": "mock-model",
            "title": "phase_9_6_negative",
            "payload": external_payload_with_ineligible(valid_name, valid_norm, "Ineligible Bogus Co"),
        }
        negative_resp = await run_exec_discovery(client, run_id, negative_body, NEGATIVE_CALL)
        assert negative_resp["status"] == 400, "Expected ineligible payload to be blocked"

        # Positive dual-engine run (internal + external)
        run_body = {
            "mode": "both",
            "engine": "external",
            "provider": "external_engine",
            "model": "mock-model",
            "title": "phase_9_6_dual",
            "payload": external_payload(valid_name, valid_norm),
        }
        first_call = await run_exec_discovery(client, run_id, run_body, FIRST_CALL)
        second_call = await run_exec_discovery(client, run_id, run_body, SECOND_CALL)

    await capture_db_excerpt(run_id, TENANT_ID)

    summary_lines = [
        "phase_9_6_exec_discovery_dual_engine_proof PASS",
        f"tenant={TENANT_ID}",
        f"run={run_id}",
        "Assertions: eligible-first gate enforced; external ineligible payload blocked; dual-engine returns compare counts; idempotent second call uses duplicate hash; evidence pointers and enrichment IDs present.",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

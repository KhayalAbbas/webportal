"""Phase 9.2 SeedListProvider deterministic proof."""

import asyncio
import json
import sys
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from uuid import UUID, uuid4
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.company_research import (  # noqa: E402
    CompanyProspect,
    CompanyProspectEvidence,
    ResearchSourceDocument,
)
from app.models.ai_enrichment_record import AIEnrichmentRecord  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.workers.company_research_worker import run_worker  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

OPENAPI_AFTER_PATH = ARTIFACT_DIR / "phase_9_2_openapi_after.json"
OPENAPI_AFTER_EXCERPT_PATH = ARTIFACT_DIR / "phase_9_2_openapi_after_excerpt.txt"
PROOF_TXT_PATH = ARTIFACT_DIR / "phase_9_2_proof.txt"
PROOF_CONSOLE_PATH = ARTIFACT_DIR / "phase_9_2_proof_console.txt"
FIRST_CALL_PATH = ARTIFACT_DIR / "phase_9_2_first_call.json"
SECOND_CALL_PATH = ARTIFACT_DIR / "phase_9_2_second_call.json"
DB_EXCERPT_PATH = ARTIFACT_DIR / "phase_9_2_db_excerpt.txt"


@contextmanager
def start_fixture_server(port: int = 8799):
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
        "source_label": "seed_list_proof",
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


async def _get_default_role(session):
    result = await session.execute(select(Role).limit(1))
    return result.scalar_one_or_none()


async def _create_run(session, tenant_id: str, role_id: UUID):
    service = CompanyResearchService(session)
    run = await service.create_research_run(
        tenant_id=tenant_id,
        data=CompanyResearchRunCreate(
            role_mandate_id=role_id,
            name="Phase 9.2 Seed List Proof",
            description="Seed provider proof harness",
            sector="Testing",
            region_scope=["US"],
            status="planned",
        ),
        created_by_user_id=None,
    )
    await session.commit()
    return run


async def _db_excerpt(run_id: UUID, tenant_id):
    async with AsyncSessionLocal() as session:
        sources = (
            await session.execute(
                select(ResearchSourceDocument).where(
                    ResearchSourceDocument.company_research_run_id == run_id,
                    ResearchSourceDocument.tenant_id == tenant_id,
                )
            )
        ).scalars().all()

        enrichments = (
            await session.execute(
                select(AIEnrichmentRecord).where(
                    AIEnrichmentRecord.company_research_run_id == run_id,
                    AIEnrichmentRecord.tenant_id == tenant_id,
                )
            )
        ).scalars().all()

        prospects = (
            await session.execute(
                select(CompanyProspect).where(
                    CompanyProspect.company_research_run_id == run_id,
                    CompanyProspect.tenant_id == tenant_id,
                )
            )
        ).scalars().all()

        prospect_ids = [p.id for p in prospects]
        evidence = []
        if prospect_ids:
            evidence = (
                await session.execute(
                    select(CompanyProspectEvidence).where(
                        CompanyProspectEvidence.company_prospect_id.in_(prospect_ids),
                        CompanyProspectEvidence.tenant_id == tenant_id,
                    )
                )
            ).scalars().all()

        def _src_row(src: ResearchSourceDocument) -> dict:
            return {
                "id": str(src.id),
                "source_type": src.source_type,
                "url": src.url,
                "status": src.status,
                "content_hash": src.content_hash,
                "meta": src.meta,
                "fetched_at": src.fetched_at.isoformat() if src.fetched_at else None,
            }

        return {
            "sources": [_src_row(s) for s in sources],
            "enrichments": [
                {
                    "id": str(en.id),
                    "provider": en.provider,
                    "purpose": en.purpose,
                    "content_hash": en.content_hash,
                    "input_scope_hash": en.input_scope_hash,
                    "source_document_id": str(en.source_document_id) if en.source_document_id else None,
                }
                for en in enrichments
            ],
            "prospects": [
                {
                    "id": str(p.id),
                    "name": p.name_normalized,
                    "discovered_by": p.discovered_by,
                    "verification_status": p.verification_status,
                }
                for p in prospects
            ],
            "evidence": [
                {
                    "id": str(ev.id),
                    "company_prospect_id": str(ev.company_prospect_id),
                    "source_url": ev.source_url,
                    "source_document_id": str(ev.source_document_id) if ev.source_document_id else None,
                    "source_content_hash": ev.source_content_hash,
                }
                for ev in evidence
            ],
            "counts": {
                "sources": len(sources),
                "enrichments": len(enrichments),
                "prospects": len(prospects),
                "evidence": len(evidence),
            },
        }


async def _start_run_and_worker(tenant_id: str, run_id: UUID):
    async with AsyncSessionLocal() as session:
        service = CompanyResearchService(session)
        await service.start_run(tenant_id=tenant_id, run_id=run_id)
        await session.commit()
    await run_worker(loop=False, sleep_seconds=0)
    await run_worker(loop=False, sleep_seconds=0)


async def main():
    async with AsyncSessionLocal() as session:
        role = await _get_default_role(session)
        if not role:
            raise RuntimeError("No role found")
        tenant_uuid = role.tenant_id
        tenant_id = str(tenant_uuid)
        run = await _create_run(session, tenant_id, role.id)

    stub_user = SimpleNamespace(id=uuid4(), tenant_id=tenant_uuid, role="admin")
    app.dependency_overrides[verify_user_tenant_access] = lambda: stub_user

    results = {}
    with start_fixture_server() as (server, base_url):
        async with AsyncClient(app=app, base_url="http://testserver") as client:
            health_resp = await client.get("/health")
            openapi_resp = await client.get("/openapi.json")
            openapi_json = openapi_resp.json()

            url = f"/company-research/runs/{run.id}/discovery/providers/seed_list/run"
            request_body = {"request": seed_payload(base_url)}
            call1 = await client.post(url, json=request_body)
            call2 = await client.post(url, json=request_body)

        await _start_run_and_worker(tenant_id, run.id)

        async with AsyncClient(app=app, base_url="http://testserver") as client:
            openapi_after_resp = await client.get("/openapi.json")
            openapi_after_json = openapi_after_resp.json()

        results["health"] = {"status": health_resp.status_code, "body": health_resp.json()}
        results["call1"] = {"status": call1.status_code, "body": call1.json()}
        results["call2"] = {"status": call2.status_code, "body": call2.json()}
        results["openapi_after"] = openapi_after_json
        results["openapi_excerpt"] = {
            "/company-research/runs/{run_id}/discovery/providers/{provider_key}/run": openapi_after_json.get("paths", {}).get(
                "/company-research/runs/{run_id}/discovery/providers/{provider_key}/run"
            ),
            "schemas": {
                k: v
                for k, v in openapi_after_json.get("components", {}).get("schemas", {}).items()
                if "DiscoveryProvider" in k or "SeedList" in k
            },
        }

    FIRST_CALL_PATH.write_text(json.dumps(results["call1"], indent=2), encoding="utf-8")
    SECOND_CALL_PATH.write_text(json.dumps(results["call2"], indent=2), encoding="utf-8")
    OPENAPI_AFTER_PATH.write_text(json.dumps(results["openapi_after"], indent=2), encoding="utf-8")
    excerpt_lines = ["PATH EXCERPT", json.dumps(results["openapi_excerpt"], indent=2)]
    OPENAPI_AFTER_EXCERPT_PATH.write_text("\n".join(excerpt_lines), encoding="utf-8")

    db_state = await _db_excerpt(run.id, tenant_uuid)
    results["db_state"] = db_state
    DB_EXCERPT_PATH.write_text(json.dumps(db_state, indent=2), encoding="utf-8")

    call1_body = results["call1"]["body"]
    call2_body = results["call2"]["body"]

    assertions = []

    def _ok(condition: bool, message: str):
        assertions.append(f"{'PASS' if condition else 'FAIL'} - {message}")
        return condition

    _ok(call2_body.get("skipped") is True, "second call flagged as skipped")
    _ok(call2_body.get("reason") == "duplicate_hash", "second call reason duplicate_hash")
    _ok(call2_body.get("source_id") == call1_body.get("source_id"), "second call reused source_id")
    _ok(call2_body.get("enrichment_id") == call1_body.get("enrichment_id"), "second call reused enrichment_id")
    _ok(call2_body.get("content_hash") == call1_body.get("content_hash"), "content_hash stable across calls")
    _ok(call2_body.get("raw_source_id") == call1_body.get("raw_source_id"), "raw_source_id stable across calls")
    _ok(results["call1"]["status"] == 200 and results["call2"]["status"] == 200, "both calls succeeded (200)")

    hashes = [src.get("content_hash") for src in db_state.get("sources", []) if src.get("content_hash")]
    _ok(len(hashes) == len(set(hashes)), "no duplicate source content_hash values in DB excerpt")

    url_sources = [s for s in db_state.get("sources", []) if s.get("source_type") == "url"]
    fetched_sources = [s for s in url_sources if s.get("status") in {"fetched", "processed"}]
    _ok(bool(fetched_sources), "URL sources fetched")
    extracted = [s for s in url_sources if (s.get("meta") or {}).get("processed_summary")]
    _ok(bool(extracted), "URL sources extracted")

    enrichment_map = {en.get("content_hash"): en for en in db_state.get("enrichments", [])}
    _ok(call1_body.get("content_hash") in enrichment_map, "enrichment recorded with content_hash")

    proof_status = "PASS" if all(a.startswith("PASS") for a in assertions) else "FAIL"

    lines = [
        "PHASE 9.2 SEED LIST PROVIDER PROOF",
        "===================================",
        f"Status: {proof_status}",
        f"Run ID: {run.id}",
        f"Tenant ID: {tenant_id}",
        "",
        "Health:",
        json.dumps(results["health"], indent=2),
        "",
        "First call:",
        json.dumps(results["call1"], indent=2),
        "",
        "Second call (idempotency check):",
        json.dumps(results["call2"], indent=2),
        "",
        "DB excerpt:",
        json.dumps(db_state, indent=2),
        "",
        "Assertions:",
        "\n".join(assertions),
        "",
        f"OpenAPI saved to: {OPENAPI_AFTER_PATH}",
        f"OpenAPI excerpt: {OPENAPI_AFTER_EXCERPT_PATH}",
        f"First call: {FIRST_CALL_PATH}",
        f"Second call: {SECOND_CALL_PATH}",
        f"DB excerpt: {DB_EXCERPT_PATH}",
    ]

    PROOF_TXT_PATH.write_text("\n".join(lines), encoding="utf-8")
    PROOF_CONSOLE_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())

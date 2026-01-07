"""Phase 9.3 GoogleSearchProvider proof (offline + idempotent).

This proof:
- Forces google_search provider to use a local Custom Search JSON fixture
- Calls the discovery provider twice to prove idempotent ingestion
- Captures DB excerpts (sources, enrichments, prospects, evidence)
- Captures OpenAPI after changes and excerpts new schemas
- Writes artifacts under scripts/proofs/_artifacts
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.ai_enrichment_record import AIEnrichmentRecord  # noqa: E402
from app.models.company_research import (  # noqa: E402
    CompanyProspect,
    CompanyProspectEvidence,
    ResearchSourceDocument,
)
from app.models.role import Role  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

OPENAPI_AFTER_PATH = ARTIFACT_DIR / "phase_9_3_openapi_after.json"
OPENAPI_AFTER_EXCERPT_PATH = ARTIFACT_DIR / "phase_9_3_openapi_after_excerpt.txt"
PROOF_TXT_PATH = ARTIFACT_DIR / "phase_9_3_proof.txt"
PROOF_CONSOLE_PATH = ARTIFACT_DIR / "phase_9_3_proof_console.txt"
FIRST_CALL_PATH = ARTIFACT_DIR / "phase_9_3_first_call.json"
SECOND_CALL_PATH = ARTIFACT_DIR / "phase_9_3_second_call.json"
DB_EXCERPT_PATH = ARTIFACT_DIR / "phase_9_3_db_excerpt.txt"


async def _get_default_role(session):
    result = await session.execute(select(Role).limit(1))
    return result.scalar_one_or_none()


async def _create_run(session, tenant_id: str, role_id: UUID):
    service = CompanyResearchService(session)
    run = await service.create_research_run(
        tenant_id=tenant_id,
        data=CompanyResearchRunCreate(
            role_mandate_id=role_id,
            name="Phase 9.3 Google Search Proof",
            description="Proof harness run",
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

        sources_sorted = sorted(sources, key=lambda s: (s.source_type or "", str(s.id)))

        return {
            "sources": [
                {
                    "id": str(src.id),
                    "source_type": src.source_type,
                    "content_hash": src.content_hash,
                    "url": src.url,
                    "status": src.status,
                    "meta": src.meta,
                }
                for src in sources_sorted
            ],
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


def _seed_env_for_fixture():
    fixture_path = ROOT / "scripts" / "proofs" / "fixtures" / "phase_9_3_google_cse_fixture.json"
    os.environ["GOOGLE_CSE_FIXTURE_PATH"] = str(fixture_path)
    os.environ["GOOGLE_CSE_API_KEY"] = "offline-api-key"
    os.environ["GOOGLE_CSE_CX"] = "offline-cx"
    settings.GOOGLE_CSE_API_KEY = "offline-api-key"
    settings.GOOGLE_CSE_CX = "offline-cx"


async def main():
    _seed_env_for_fixture()

    async with AsyncSessionLocal() as session:
        role = await _get_default_role(session)
        if not role:
            raise RuntimeError("No role found to seed run")
        tenant_uuid = role.tenant_id
        tenant_id = str(tenant_uuid)
        created_by = uuid4()
        run = await _create_run(session, tenant_id, role.id)

    stub_user = SimpleNamespace(id=created_by, tenant_id=tenant_uuid, role="admin")
    app.dependency_overrides[verify_user_tenant_access] = lambda: stub_user

    results = {}
    async with AsyncClient(app=app, base_url="http://testserver") as client:
        health_resp = await client.get("/health")
        openapi_resp = await client.get("/openapi.json")
        openapi_json = openapi_resp.json()
        OPENAPI_AFTER_PATH.write_text(json.dumps(openapi_json, indent=2), encoding="utf-8")

        path_key = "/company-research/runs/{run_id}/discovery/providers/{provider_key}/run"
        path_excerpt = openapi_json.get("paths", {}).get(path_key)
        schemas_excerpt = {
            k: v
            for k, v in openapi_json.get("components", {}).get("schemas", {}).items()
            if "DiscoveryProvider" in k or "GoogleSearch" in k
        }
        excerpt_lines = [
            "PATH EXCERPT",
            json.dumps({path_key: path_excerpt}, indent=2),
            "",
            "SCHEMAS",
            json.dumps(schemas_excerpt, indent=2),
        ]
        OPENAPI_AFTER_EXCERPT_PATH.write_text("\n".join(excerpt_lines), encoding="utf-8")

        url = f"/company-research/runs/{run.id}/discovery/providers/google_search/run"
        request_body = {
            "request": {
                "query": "climate analytics startups",
                "country": "US",
                "language": "en",
                "num_results": 2,
                "site_filter": "example.com",
            }
        }
        call1 = await client.post(url, json=request_body)
        call2 = await client.post(url, json=request_body)

        results["health"] = {"status": health_resp.status_code, "body": health_resp.json()}
        results["call1"] = {"status": call1.status_code, "body": call1.json()}
        results["call2"] = {"status": call2.status_code, "body": call2.json()}

    FIRST_CALL_PATH.write_text(json.dumps(results["call1"], indent=2), encoding="utf-8")
    SECOND_CALL_PATH.write_text(json.dumps(results["call2"], indent=2), encoding="utf-8")

    db_state = await _db_excerpt(run.id, tenant_uuid)
    results["db_state"] = db_state
    DB_EXCERPT_PATH.write_text(json.dumps(db_state, indent=2), encoding="utf-8")

    # Assertions
    assertions = []

    def _ok(condition: bool, message: str):
        assertions.append(f"{'PASS' if condition else 'FAIL'} - {message}")
        return condition

    call1_body = results["call1"]["body"]
    call2_body = results["call2"]["body"]

    _ok(results["health"]["status"] == 200, "health endpoint returns 200")
    _ok(not call1_body.get("error"), "first call succeeded without provider error")
    _ok(call1_body.get("source_id") is not None, "first call produced source_id")
    _ok(call1_body.get("envelope_source_id") is not None, "envelope source captured on first call")

    skipped = bool(call2_body.get("skipped"))
    _ok(skipped, "second call flagged as skipped")
    _ok(call2_body.get("source_id") == call1_body.get("source_id"), "second call reused source_id")
    _ok(call2_body.get("enrichment_id") == call1_body.get("enrichment_id"), "second call reused enrichment_id")
    _ok(call2_body.get("content_hash") == call1_body.get("content_hash"), "content_hash stable across calls")
    _ok(call2_body.get("envelope_source_id") == call1_body.get("envelope_source_id"), "envelope source reused across calls")

    hashes = [src.get("content_hash") for src in db_state.get("sources", []) if src.get("content_hash")]
    _ok(len(hashes) == len(set(hashes)), "no duplicate source content_hash values in DB excerpt")

    enrichment_hashes = [en.get("input_scope_hash") for en in db_state.get("enrichments", [])]
    _ok(all(h == call1_body.get("content_hash") for h in enrichment_hashes), "input_scope_hash aligns with content_hash")

    url_sources = [s for s in db_state.get("sources", []) if s.get("source_type") == "url"]
    _ok(len(url_sources) == 2, "url sources created for evidence URLs")

    proof_status = "PASS" if all(a.startswith("PASS") for a in assertions) else "FAIL"

    lines = [
        "PHASE 9.3 GOOGLE SEARCH PROVIDER PROOF",
        "=======================================",
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

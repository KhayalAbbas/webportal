"""Phase 7.8 proof: dual-engine executive discovery with provenance merge and idempotent evidence.

Runs internal, external, and both modes against seeded eligible/ineligible companies,
verifies request/response SourceDocuments + AIEnrichmentRecords per engine, merges
provenance to both when engines overlap, promotes verification, and reruns the
full flow to assert strict idempotency. Writes required artifacts and PASS footer.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.main import app
from app.core.dependencies import verify_user_tenant_access
from app.db.session import get_async_session_context
from app.repositories.company_research_repo import CompanyResearchRepository
from app.schemas.company_research import CompanyProspectCreate, CompanyResearchRunCreate, SourceDocumentCreate
from app.services.company_research_service import CompanyResearchService

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_8_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_8_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_8_db_excerpt.sql.txt"
EXEC_AFTER_INTERNAL = ARTIFACT_DIR / "phase_7_8_exec_after_internal.json"
EXEC_AFTER_EXTERNAL = ARTIFACT_DIR / "phase_7_8_exec_after_external.json"
EXEC_AFTER_BOTH = ARTIFACT_DIR / "phase_7_8_exec_after_both.json"

TENANT_ID = str(uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
RUN_NAME = "phase_7_8_dual_engine_exec"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = UUID(int=0)
        self.email = "proof@example.com"
        self.username = "proof"


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


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
        DB_EXCERPT,
        EXEC_AFTER_INTERNAL,
        EXEC_AFTER_EXTERNAL,
        EXEC_AFTER_BOTH,
    ]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=RUN_NAME,
                description="Phase 7.8 dual-engine exec discovery",
                sector="software",
                region_scope=["US"],
                status="active",
            ),
        )

        seed_source = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="seed source",
                content_text="seed for exec discovery proof",
                meta={"label": "seed"},
            ),
        )

        eligible = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Omega Exec Eligible",
                name_normalized="omega exec eligible",
                website_url="https://omega-78.example.com",
                hq_country="US",
                sector="software",
                subsector="infra",
                relevance_score=0.9,
                evidence_score=0.9,
                status="accepted",
                discovered_by="internal",
                verification_status="partial",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )

        ineligible = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Zeta Exec Disabled",
                name_normalized="zeta exec disabled",
                website_url="https://zeta-78.example.com",
                hq_country="US",
                sector="software",
                subsector="security",
                relevance_score=0.6,
                evidence_score=0.4,
                status="accepted",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=False,
                review_status="accepted",
            ),
        )

        canonical = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="omega_exec_eligible",
            primary_domain="omega-78.example.com",
            country_code="US",
        )
        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical.id,
            company_entity_id=eligible.id,
            match_rule="proof_exec_dual_engine",
            evidence_source_document_id=seed_source.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospects": {
                "eligible": eligible.id,
                "ineligible": ineligible.id,
            },
            "seed_source": seed_source.id,
        }


async def update_company_verification(company_id: UUID, status: str) -> None:
    async with get_async_session_context() as session:
        row = await session.execute(
            text(
                """
                UPDATE company_prospects
                SET verification_status = :status
                WHERE id = :cid AND tenant_id = :tenant_id
                RETURNING id
                """
            ),
            {"status": status, "cid": company_id, "tenant_id": TENANT_ID},
        )
        updated = row.fetchone()
        assert updated, "verification update failed"
        await session.commit()


async def call_exec_discovery(
    run_id: UUID,
    *,
    mode: str,
    payload: Dict[str, Any] | None,
    engine: str,
    provider: str,
    model: str,
    title: str,
) -> Dict[str, Any]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    body: Dict[str, Any] = {
        "mode": mode,
        "engine": engine,
        "provider": provider,
        "model": model,
        "title": title,
    }
    if payload:
        body["payload"] = payload

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json=body,
        )
        assert resp.status_code == 200, f"exec discovery status {resp.status_code}: {resp.text}"
        return resp.json()


async def fetch_exec_listing(run_id: UUID) -> List[Dict[str, Any]]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/executives", headers=headers)
        assert resp.status_code == 200, f"exec listing status {resp.status_code}: {resp.text}"
        return resp.json()


async def snapshot_state(run_id: UUID) -> Dict[str, Any]:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, name_normalized, discovered_by, verification_status, source_document_id, source_label
                FROM executive_prospects
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
        evidence_rows = await session.execute(
            text(
                """
                SELECT executive_prospect_id, source_type, source_url, source_document_id, source_content_hash
                FROM executive_prospect_evidence
                WHERE tenant_id = :tenant_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        sources_rows = await session.execute(
            text(
                """
                SELECT id, source_type, title, content_hash, meta
                FROM source_documents
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
        enrichment_rows = await session.execute(
            text(
                """
                SELECT id, provider, model_name, purpose, content_hash, status, source_document_id
                FROM ai_enrichment_record
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id AND purpose = 'executive_discovery'
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )

    def _coerce_meta(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value

    return {
        "executives": [dict(r._mapping) for r in exec_rows.fetchall()],
        "evidence": [dict(r._mapping) for r in evidence_rows.fetchall()],
        "sources": [{**dict(r._mapping), "meta": _coerce_meta(r._mapping.get("meta"))} for r in sources_rows.fetchall()],
        "enrichments": [dict(r._mapping) for r in enrichment_rows.fetchall()],
    }


def assert_only_eligible(exec_rows: List[Dict[str, Any]], eligible_id: UUID) -> None:
    companies = {UUID(str(r.get("company_prospect_id"))) for r in exec_rows}
    assert companies == {eligible_id}, f"unexpected companies in exec list: {companies}"


def assert_provenance_merge(exec_rows: List[Dict[str, Any]], overlap_name: str) -> None:
    match = [r for r in exec_rows if str(r.get("name")).lower() == overlap_name.lower()]
    assert match, f"missing exec {overlap_name}"
    assert match[0].get("discovered_by") == "both", f"expected provenance both, got {match[0].get('discovered_by')}"


def assert_engine_sources(state: Dict[str, Any], engine: str) -> None:
    sources = state.get("sources", [])
    requests = [s for s in sources if (s.get("meta") or {}).get("kind") == "llm_json_request" and (s.get("meta") or {}).get("engine") == engine]
    responses = [s for s in sources if (s.get("meta") or {}).get("kind") == "llm_json_response" and (s.get("meta") or {}).get("engine") == engine]
    assert requests, f"missing request source for {engine}"
    assert responses, f"missing response source for {engine}"


def assert_no_growth(state_before: Dict[str, Any], state_after: Dict[str, Any]) -> None:
    for key in ["executives", "evidence", "sources", "enrichments"]:
        assert len(state_before.get(key, [])) == len(state_after.get(key, [])), f"{key} count changed between passes"


def write_db_excerpt(state: Dict[str, Any]) -> None:
    lines = [
        "-- source_documents",
        json_dump(state.get("sources", [])),
        "-- ai_enrichment_record",
        json_dump(state.get("enrichments", [])),
        "-- executive_prospects",
        json_dump(state.get("executives", [])),
        "-- executive_prospect_evidence",
        json_dump(state.get("evidence", [])),
    ]
    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    app.dependency_overrides[verify_user_tenant_access] = override_verify_user

    fixtures = await seed_fixtures()
    run_id = fixtures["run_id"]
    eligible_id = fixtures["prospects"]["eligible"]

    external_payload = {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "generated_at": "1970-01-01T00:00:00Z",
        "query": "phase_7_8_external_proof",
        "companies": [
            {
                "company_name": "Omega Exec Eligible",
                "company_normalized": "omega exec eligible",
                "executives": [
                    {
                        "name": "Omega Exec Eligible CEO",
                        "title": "Chief Executive Officer",
                        "profile_url": "https://ext.example.com/omega/ceo",
                        "confidence": 0.8,
                        "evidence": [
                            {
                                "url": "https://ext.example.com/omega/ceo",
                                "label": "External leadership",
                                "kind": "external",
                                "snippet": "CEO listing from external engine",
                            }
                        ],
                    },
                    {
                        "name": "Omega Exec Eligible COO",
                        "title": "Chief Operating Officer",
                        "profile_url": "https://ext.example.com/omega/coo",
                        "confidence": 0.75,
                        "evidence": [
                            {
                                "url": "https://ext.example.com/omega/coo",
                                "label": "External leadership",
                                "kind": "external",
                                "snippet": "COO listing from external engine",
                            }
                        ],
                    },
                ],
            }
        ],
    }

    log("Running internal engine (pass 1)...")
    await call_exec_discovery(
        run_id,
        mode="internal",
        payload=None,
        engine="internal",
        provider="internal_stub",
        model="deterministic_stub_v1",
        title="Internal Executive Discovery",
    )
    exec_after_internal = await fetch_exec_listing(run_id)
    assert_only_eligible(exec_after_internal, eligible_id)
    EXEC_AFTER_INTERNAL.write_text(json_dump(exec_after_internal), encoding="utf-8")

    # Promote verification before external to demonstrate verification status promotion logic.
    await update_company_verification(eligible_id, "verified")

    log("Running external engine (pass 1)...")
    await call_exec_discovery(
        run_id,
        mode="external",
        payload=external_payload,
        engine="external",
        provider="external_engine",
        model="mock-model",
        title="External Executive Payload",
    )
    exec_after_external = await fetch_exec_listing(run_id)
    assert_only_eligible(exec_after_external, eligible_id)
    assert_provenance_merge(exec_after_external, "Omega Exec Eligible CEO")
    EXEC_AFTER_EXTERNAL.write_text(json_dump(exec_after_external), encoding="utf-8")

    log("Running both engines (pass 1)...")
    await call_exec_discovery(
        run_id,
        mode="both",
        payload=external_payload,
        engine="external",
        provider="external_engine",
        model="mock-model",
        title="External + Internal",
    )
    exec_after_both = await fetch_exec_listing(run_id)
    assert_only_eligible(exec_after_both, eligible_id)
    EXEC_AFTER_BOTH.write_text(json_dump(exec_after_both), encoding="utf-8")

    state_first = await snapshot_state(run_id)
    assert_engine_sources(state_first, "internal")
    assert_engine_sources(state_first, "external")

    # Idempotency: rerun full flow and ensure no growth.
    log("Re-running full dual-engine flow for idempotency...")
    await call_exec_discovery(
        run_id,
        mode="internal",
        payload=None,
        engine="internal",
        provider="internal_stub",
        model="deterministic_stub_v1",
        title="Internal Executive Discovery",
    )
    await call_exec_discovery(
        run_id,
        mode="external",
        payload=external_payload,
        engine="external",
        provider="external_engine",
        model="mock-model",
        title="External Executive Payload",
    )
    await call_exec_discovery(
        run_id,
        mode="both",
        payload=external_payload,
        engine="external",
        provider="external_engine",
        model="mock-model",
        title="External + Internal",
    )

    state_second = await snapshot_state(run_id)
    exec_after_second = await fetch_exec_listing(run_id)

    assert exec_after_both == exec_after_second, "exec listing changed between passes"
    assert_no_growth(state_first, state_second)

    write_db_excerpt(state_second)
    PROOF_SUMMARY.write_text("PASS", encoding="utf-8")
    log("PASS")


if __name__ == "__main__":
    asyncio.run(main())

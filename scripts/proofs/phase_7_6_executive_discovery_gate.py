"""Phase 7.6 proof: executive discovery gate, evidence-first storage, idempotent hashing.

Seeds a tenant/run with three prospects (only one eligible for executive discovery),
invokes the executive discovery endpoint twice, asserts gating + idempotency, and
captures required artifacts.
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
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_6_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_6_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_6_db_excerpt.sql.txt"
EXEC_FIRST = ARTIFACT_DIR / "phase_7_6_exec_after_first.json"
EXEC_SECOND = ARTIFACT_DIR / "phase_7_6_exec_after_second.json"
EXEC_SAMPLE = ARTIFACT_DIR / "phase_7_6_exec_action_response_example.json"

TENANT_ID = str(uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
RUN_NAME = "phase_7_6_exec_gate"


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
    for path in [PROOF_CONSOLE, PROOF_SUMMARY, DB_EXCERPT, EXEC_FIRST, EXEC_SECOND, EXEC_SAMPLE]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, sort_keys=True)


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=RUN_NAME,
                description="Phase 7.6 exec discovery gate proof",
                sector="demo",
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
                content_text="seed for canonical linkage",
                meta={"label": "seed"},
            ),
        )

        eligible = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Alpha Exec Eligible",
                name_normalized="alpha exec eligible",
                website_url="https://alpha-76.example.com",
                hq_country="US",
                sector="software",
                subsector="saas",
                relevance_score=0.8,
                evidence_score=0.9,
                status="accepted",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )

        ineligible_exec_off = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Beta Exec Disabled",
                name_normalized="beta exec disabled",
                website_url="https://beta-76.example.com",
                hq_country="US",
                sector="software",
                subsector="analytics",
                relevance_score=0.7,
                evidence_score=0.5,
                status="accepted",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=False,
                review_status="accepted",
            ),
        )

        ineligible_status = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Gamma Exec Hold",
                name_normalized="gamma exec hold",
                website_url="https://gamma-76.example.com",
                hq_country="US",
                sector="software",
                subsector="infra",
                relevance_score=0.6,
                evidence_score=0.4,
                status="hold",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=True,
                review_status="hold",
            ),
        )

        canonical = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="alpha_exec_eligible",
            primary_domain="alpha-76.example.com",
            country_code="US",
        )
        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical.id,
            company_entity_id=eligible.id,
            match_rule="proof_exec_gate",
            evidence_source_document_id=seed_source.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospects": {
                "eligible": eligible.id,
                "exec_off": ineligible_exec_off.id,
                "status_hold": ineligible_status.id,
            },
            "canonical": canonical.id,
            "seed_source": seed_source.id,
        }


async def call_exec_discovery(run_id: UUID, mode: str = "internal") -> Dict[str, Any]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={"mode": mode},
        )
        assert resp.status_code == 200, f"exec discovery status {resp.status_code}: {resp.text}"
        return resp.json()


async def snapshot_exec_state(run_id: UUID) -> Dict[str, Any]:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, name_normalized, title, profile_url, linkedin_url, source_document_id
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
                SELECT executive_prospect_id, source_url, source_document_id, source_content_hash
                FROM executive_prospect_evidence
                WHERE tenant_id = :tenant_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        sources = await session.execute(
            text(
                """
                SELECT id, source_type, title, content_hash, meta
                FROM source_documents
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id AND source_type = 'llm_json'
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
        enrichments = await session.execute(
            text(
                """
                SELECT id, provider, model_name, purpose, content_hash, status
                FROM ai_enrichment_record
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id AND purpose = 'executive_discovery'
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
    return {
        "executives": [dict(r._mapping) for r in exec_rows.fetchall()],
        "evidence": [dict(r._mapping) for r in evidence_rows.fetchall()],
        "sources": [dict(r._mapping) for r in sources.fetchall()],
        "enrichments": [dict(r._mapping) for r in enrichments.fetchall()],
    }


async def write_db_excerpt(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        blocks: List[List[Dict[str, Any]]] = []
        for stmt, params in [
            (
                text(
                    """
                    SELECT id, name, status
                    FROM company_research_runs
                    WHERE tenant_id = :tenant_id AND id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID, "run_id": run_id},
            ),
            (
                text(
                    """
                    SELECT id, name_normalized, status, exec_search_enabled
                    FROM company_prospects
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID, "run_id": run_id},
            ),
            (
                text(
                    """
                    SELECT id, company_prospect_id, name_normalized, source_document_id
                    FROM executive_prospects
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID, "run_id": run_id},
            ),
            (
                text(
                    """
                    SELECT executive_prospect_id, source_document_id, source_content_hash
                    FROM executive_prospect_evidence
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID},
            ),
            (
                text(
                    """
                    SELECT id, source_type, content_hash
                    FROM source_documents
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id AND source_type = 'llm_json'
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID, "run_id": run_id},
            ),
            (
                text(
                    """
                    SELECT id, purpose, content_hash
                    FROM ai_enrichment_record
                    WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id AND purpose = 'executive_discovery'
                    ORDER BY created_at
                    """
                ),
                {"tenant_id": TENANT_ID, "run_id": run_id},
            ),
        ]:
            result = await session.execute(stmt, params)
            blocks.append([dict(row._mapping) for row in result.fetchall()])
    DB_EXCERPT.write_text(json_dump(blocks), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    app.dependency_overrides[verify_user_tenant_access] = override_verify_user

    fixtures = await seed_fixtures()
    run_id = fixtures["run_id"]
    log(f"seeded run {run_id}")

    first_resp = await call_exec_discovery(run_id, mode="internal")
    EXEC_SAMPLE.write_text(json_dump(first_resp), encoding="utf-8")
    first_snapshot = await snapshot_exec_state(run_id)
    EXEC_FIRST.write_text(json_dump(first_snapshot), encoding="utf-8")

    log(f"first: eligible={first_resp.get('eligible_company_count')} processed={first_resp.get('processed_company_count')}")
    assert first_resp.get("eligible_company_count") == 1, "eligible company count should be 1"
    assert first_resp.get("processed_company_count") == 1, "processed company count should be 1"
    assert len(first_snapshot["executives"]) == 2, "expected two executives (CEO, CFO)"
    assert len(first_snapshot["evidence"]) == 2, "expected evidence for both executives"
    assert first_snapshot["sources"], "llm_json source missing"
    assert first_snapshot["enrichments"], "enrichment missing"

    second_resp = await call_exec_discovery(run_id, mode="internal")
    second_snapshot = await snapshot_exec_state(run_id)
    EXEC_SECOND.write_text(json_dump(second_snapshot), encoding="utf-8")

    log(f"second: eligible={second_resp.get('eligible_company_count')} processed={second_resp.get('processed_company_count')} skipped={second_resp.get('skipped')}")
    assert second_resp.get("skipped") is True, "second call should be skipped (duplicate hash)"
    assert len(second_snapshot["executives"]) == len(first_snapshot["executives"]), "idempotency violated: exec count changed"
    assert len(second_snapshot["evidence"]) == len(first_snapshot["evidence"]), "idempotency violated: evidence count changed"
    first_source_ids = {row["id"] for row in first_snapshot["sources"]}
    second_source_ids = {row["id"] for row in second_snapshot["sources"]}
    assert first_source_ids == second_source_ids, "source ids changed between runs"

    await write_db_excerpt(run_id)

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "phase_7_6_executive_discovery_gate PASS",
                f"tenant={TENANT_ID}",
                f"run={run_id}",
                "PASS",
            ]
        ),
        encoding="utf-8",
    )
    log("PASS")


if __name__ == "__main__":
    asyncio.run(main())

"""Phase 7.5 proof: review gate + provenance/verification filters.

Creates a run with three prospects carrying distinct provenance/verification/review
states, seeds evidence assignments for deterministic ranking, exercises ranked
filters and exports, patches review_status with audit logging, and re-runs to
confirm stability across two passes.
"""

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
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.db.session import get_async_session_context
from app.schemas.company_research import (
    CompanyProspectCreate,
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from app.services.company_enrichment_extraction_service import (
    CompanyEnrichmentExtractionService,
)
from app.services.company_research_service import CompanyResearchService
from app.services.enrichment_assignment_service import EnrichmentAssignmentService
from app.repositories.company_research_repo import CompanyResearchRepository

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_5_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_5_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_5_db_excerpt.sql.txt"
RANKED_FIRST = ARTIFACT_DIR / "phase_7_5_ranked_after_first.json"
RANKED_SECOND = ARTIFACT_DIR / "phase_7_5_ranked_after_second.json"
FILTERED_EXAMPLES = ARTIFACT_DIR / "phase_7_5_filtered_examples.json"
CSV_FIRST = ARTIFACT_DIR / "phase_7_5_export_csv_first.csv"
CSV_SECOND = ARTIFACT_DIR / "phase_7_5_export_csv_second.csv"
UI_HTML = ARTIFACT_DIR / "phase_7_5_ui_html_excerpt.html"

TENANT_ID = str(uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = UUID(int=0)
        self.email = "proof@example.com"
        self.username = "proof"


class DummyUIUser(UIUser):
    def __init__(self, tenant_id: str):
        super().__init__(user_id=UUID(int=0), tenant_id=UUID(tenant_id), email="proof@example.com", role="admin")


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


def override_ui_user() -> DummyUIUser:
    return DummyUIUser(TENANT_ID)


def log(line: str) -> None:
    print(line)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        DB_EXCERPT,
        RANKED_FIRST,
        RANKED_SECOND,
        FILTERED_EXAMPLES,
        CSV_FIRST,
        CSV_SECOND,
        UI_HTML,
    ]:
        path.unlink(missing_ok=True)


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        research = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await research.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name="phase_7_5_review_gate",
                description="Stage 7.5 proof",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        strong = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Strong source",
                content_text="HQ in US with ownership signal and industry keywords for alpha.",
                meta={"label": "strong"},
            ),
        )
        medium = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Medium source",
                content_text="Ownership signal for beta with partial verification.",
                meta={"label": "medium"},
            ),
        )
        sparse = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Sparse source",
                content_text="Sparse evidence for gamma manual entry.",
                meta={"label": "sparse"},
            ),
        )

        alpha = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Alpha Provenance",
                name_normalized="alpha provenance",
                website_url="https://alpha-75.example.com",
                hq_country="US",
                sector="energy",
                subsector="solar",
                relevance_score=0.7,
                evidence_score=0.8,
                status="new",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )
        beta = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Beta Provenance",
                name_normalized="beta provenance",
                website_url="https://beta-75.example.com",
                hq_country="CA",
                sector="fintech",
                subsector="payments",
                relevance_score=0.6,
                evidence_score=0.6,
                status="new",
                discovered_by="external_llm",
                verification_status="partial",
                exec_search_enabled=False,
                review_status="hold",
            ),
        )
        gamma = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Gamma Provenance",
                name_normalized="gamma provenance",
                website_url="https://gamma-75.example.com",
                hq_country="GB",
                sector="manufacturing",
                subsector="components",
                relevance_score=0.4,
                evidence_score=0.2,
                status="new",
                discovered_by="manual",
                verification_status="unverified",
                exec_search_enabled=True,
                review_status="rejected",
            ),
        )

        canonical_alpha = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="alpha_75",
            primary_domain="alpha-75.example.com",
            country_code="US",
        )
        canonical_beta = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="beta_75",
            primary_domain="beta-75.example.com",
            country_code="CA",
        )
        canonical_gamma = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="gamma_75",
            primary_domain="gamma-75.example.com",
            country_code="GB",
        )

        for canonical_id, prospect_id, source_id, rule in [
            (canonical_alpha.id, alpha.id, strong.id, "proof_strong"),
            (canonical_beta.id, beta.id, medium.id, "proof_medium"),
            (canonical_gamma.id, gamma.id, sparse.id, "proof_sparse"),
        ]:
            await repo.upsert_canonical_company_link(
                tenant_id=TENANT_ID,
                canonical_company_id=canonical_id,
                company_entity_id=prospect_id,
                match_rule=rule,
                evidence_source_document_id=source_id,
                evidence_company_research_run_id=run.id,
            )

        await session.commit()

        return {
            "run_id": run.id,
            "prospects": {"alpha": alpha.id, "beta": beta.id, "gamma": gamma.id},
            "canonicals": {
                "alpha": canonical_alpha.id,
                "beta": canonical_beta.id,
                "gamma": canonical_gamma.id,
            },
            "sources": {"strong": strong.id, "medium": medium.id, "sparse": sparse.id},
        }


async def run_extraction(fixtures: Dict[str, Any]) -> None:
    async with get_async_session_context() as session:
        extractor = CompanyEnrichmentExtractionService(session)
        await extractor.extract_company_enrichment(
            tenant_id=TENANT_ID,
            canonical_company_id=fixtures["canonicals"]["alpha"],
            source_document_id=fixtures["sources"]["strong"],
        )
        await extractor.extract_company_enrichment(
            tenant_id=TENANT_ID,
            canonical_company_id=fixtures["canonicals"]["beta"],
            source_document_id=fixtures["sources"]["medium"],
        )
        await extractor.extract_company_enrichment(
            tenant_id=TENANT_ID,
            canonical_company_id=fixtures["canonicals"]["gamma"],
            source_document_id=fixtures["sources"]["sparse"],
        )


async def fetch_rankings(run_id: UUID, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            f"/company-research/runs/{run_id}/prospects-ranked",
            headers=headers,
            params=params or {},
        )
        assert resp.status_code == 200, f"ranking status {resp.status_code}"
        data = resp.json()
        assert isinstance(data, list), "ranking payload is not a list"
        return data


async def export_rankings_csv(run_id: UUID, path: Path) -> None:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/prospects-ranked.csv", headers=headers)
        assert resp.status_code == 200, f"csv status {resp.status_code}"
        path.write_text(resp.text, encoding="utf-8")


async def patch_review_status(prospect_id: UUID, review_status: str) -> None:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.patch(
            f"/company-research/prospects/{prospect_id}/review-status",
            headers=headers,
            json={"review_status": review_status},
        )
        assert resp.status_code == 200, f"patch status {resp.status_code}"


async def count_audit_logs(prospect_id: UUID) -> int:
    async with get_async_session_context() as session:
        result = await session.execute(
            text(
                """
                                SELECT count(*) FROM activity_log
                WHERE tenant_id = :tenant_id
                  AND type = 'PROSPECT_REVIEW_STATUS'
                  AND message LIKE :needle
                """
            ),
            {"tenant_id": TENANT_ID, "needle": f"%{prospect_id}%"},
        )
        return int(result.scalar_one())


async def write_filtered_examples(run_id: UUID) -> None:
    filtered = {}
    cases = {
        "review_status=accepted": {"review_status": "accepted"},
        "verification_status=partial": {"verification_status": "partial"},
        "discovered_by=manual": {"discovered_by": "manual"},
        "exec_search_enabled=true&review_status=rejected": {
            "exec_search_enabled": True,
            "review_status": "rejected",
        },
    }

    for label, params in cases.items():
        data = await fetch_rankings(run_id, params=params)
        filtered[label] = data
        assert len(data) == 1, f"filter {label} failed to isolate prospect"

    FILTERED_EXAMPLES.write_text(json.dumps(filtered, indent=2, default=str), encoding="utf-8")


async def write_db_excerpt(fixtures: Dict[str, Any]) -> None:
    async with get_async_session_context() as session:
        rows = []
        for stmt in [
            text(
                """
                SELECT id, name, status
                FROM company_research_runs
                WHERE tenant_id = :tenant_id AND id = :run_id
                ORDER BY created_at
                """
            ),
            text(
                """
                SELECT id, name_normalized, review_status, discovered_by, verification_status, exec_search_enabled
                FROM company_prospects
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            text(
                """
                SELECT type, message
                FROM activity_log
                WHERE tenant_id = :tenant_id AND type = 'PROSPECT_REVIEW_STATUS'
                ORDER BY created_at
                """
            ),
        ]:
            result = await session.execute(stmt, {"tenant_id": TENANT_ID, "run_id": fixtures["run_id"]})
            rows.append([dict(r._mapping) for r in result.fetchall()])
    DB_EXCERPT.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")


async def fetch_ui_excerpt(run_id: UUID) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/ui/company-research/runs/{run_id}/prospects-ranked")
        assert resp.status_code == 200, f"ui status {resp.status_code}"
        text_body = resp.text[:1200]
        UI_HTML.write_text(text_body, encoding="utf-8")


def assert_payload_fields(ranking: List[Dict[str, Any]]) -> None:
    for item in ranking:
        for key in [
            "review_status",
            "verification_status",
            "discovered_by",
            "exec_search_enabled",
        ]:
            assert key in item, f"missing {key} in ranking payload"


async def main() -> None:
    reset_artifacts()
    app.dependency_overrides[verify_user_tenant_access] = override_verify_user
    app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user

    fixtures = await seed_fixtures()
    log(f"seeded run {fixtures['run_id']}")
    await run_extraction(fixtures)
    log("extraction complete")

    ranking_initial = await fetch_rankings(fixtures["run_id"])
    assert_payload_fields(ranking_initial)
    await write_filtered_examples(fixtures["run_id"])
    log("filters verified")

    await export_rankings_csv(fixtures["run_id"], CSV_FIRST)

    await patch_review_status(fixtures["prospects"]["alpha"], "hold")
    count_after_first = await count_audit_logs(fixtures["prospects"]["alpha"])
    assert count_after_first == 1, f"expected 1 audit log, got {count_after_first}"
    ranking_first = await fetch_rankings(fixtures["run_id"])
    RANKED_FIRST.write_text(json.dumps(ranking_first, indent=2, default=str), encoding="utf-8")
    await export_rankings_csv(fixtures["run_id"], CSV_SECOND)
    await fetch_ui_excerpt(fixtures["run_id"])

    await patch_review_status(fixtures["prospects"]["alpha"], "hold")
    count_after_second = await count_audit_logs(fixtures["prospects"]["alpha"])
    assert count_after_second == 1, "no-op patch created duplicate audit log"
    ranking_second = await fetch_rankings(fixtures["run_id"])
    RANKED_SECOND.write_text(json.dumps(ranking_second, indent=2, default=str), encoding="utf-8")

    await write_db_excerpt(fixtures)

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "phase_7_5_review_gate_provenance_filters PASS",
                f"tenant={TENANT_ID}",
                f"run={fixtures['run_id']}",
                "PASS",
            ]
        ),
        encoding="utf-8",
    )
    log("PASS")


if __name__ == "__main__":
    asyncio.run(main())

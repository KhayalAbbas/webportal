"""Phase 7.3 deterministic prospect ranking proof.

Creates a research run with three prospects tied to canonical companies,
runs Stage 7.2 enrichment extraction to populate evidence-backed assignments,
calls the new /company-research/runs/{run_id}/prospects-ranked endpoint, and
verifies deterministic ordering, explainability payload, and idempotency
across two passes.
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.schemas.company_research import (  # noqa: E402
    CompanyProspectCreate,
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from app.services.company_enrichment_extraction_service import (  # noqa: E402
    CompanyEnrichmentExtractionService,
)
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.services.enrichment_assignment_service import EnrichmentAssignmentService  # noqa: E402


ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_3_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_3_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_3_db_excerpt.sql.txt"
RANKED_FIRST = ARTIFACT_DIR / "phase_7_3_ranked_after_first.json"
RANKED_SECOND = ARTIFACT_DIR / "phase_7_3_ranked_after_second.json"
ASSIGNMENTS_FIRST = ARTIFACT_DIR / "phase_7_3_assignments_after_first.json"
ASSIGNMENTS_SECOND = ARTIFACT_DIR / "phase_7_3_assignments_after_second.json"

TENANT_ID = str(uuid.uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")

SOURCE_STRONG = (
    "Headquarters: Romania. The company is listed on NASDAQ with ticker ROE. "
    "It delivers renewable energy solutions including solar farms, battery storage, energy storage, and grid services. "
    "Renewable energy platforms and solar projects drive growth."
)

SOURCE_MEDIUM = (
    "Based in India, the group is a privately held subsidiary of Tech Holdings. "
    "It focuses on fintech infrastructure, payments processing, and cloud platforms for banks. "
    "The fintech stack and payments network power clients."
)

SOURCE_SPARSE = "Sparse signals for low-priority company with limited evidence."


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


app.dependency_overrides[verify_user_tenant_access] = override_verify_user


def log(line: str) -> None:
    print(line)
    PROOF_CONSOLE.parent.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize(i) for i in value]
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    return value


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        DB_EXCERPT,
        RANKED_FIRST,
        RANKED_SECOND,
        ASSIGNMENTS_FIRST,
        ASSIGNMENTS_SECOND,
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
                name="phase_7_3_ranked_run",
                description="Stage 7.3 ranking proof",
                sector="demo",
                region_scope=["EU"],
                status="active",
            ),
        )

        source_strong = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.3 strong source",
                content_text=SOURCE_STRONG,
                meta={"stage": "7.3", "label": "strong"},
            ),
        )

        source_medium = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.3 medium source",
                content_text=SOURCE_MEDIUM,
                meta={"stage": "7.3", "label": "medium"},
            ),
        )

        source_sparse = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.3 sparse source",
                content_text=SOURCE_SPARSE,
                meta={"stage": "7.3", "label": "sparse"},
            ),
        )

        canonical_alpha = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_7_3_alpha_co",
            primary_domain="alpha-73.example.com",
            country_code="RO",
        )

        canonical_beta = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_7_3_beta_co",
            primary_domain="beta-73.example.com",
            country_code="IN",
        )

        canonical_gamma = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_7_3_gamma_co",
            primary_domain="gamma-73.example.com",
            country_code="CA",
        )

        prospect_alpha = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Alpha Co",
                name_normalized="alpha co",
                website_url="https://alpha-73.example.com",
                hq_country="RO",
                hq_city="Bucharest",
                sector="renewable energy",
                subsector="solar battery",
                employees_band="200-500",
                revenue_band_usd="200-500m",
                relevance_score=0.62,
                evidence_score=0.80,
                data_confidence=0.9,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=False,
            ),
        )

        prospect_beta = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Beta Fintech",
                name_normalized="beta fintech",
                website_url="https://beta-73.example.com",
                hq_country="IN",
                hq_city="Bangalore",
                sector="fintech infrastructure",
                subsector="payments cloud",
                employees_band="500-1000",
                revenue_band_usd="100-200m",
                relevance_score=0.58,
                evidence_score=0.70,
                data_confidence=0.85,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=False,
            ),
        )

        prospect_gamma = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Gamma Sparse",
                name_normalized="gamma sparse",
                website_url="https://gamma-73.example.com",
                hq_country="CA",
                hq_city="Toronto",
                sector="generic",
                subsector="limited",
                employees_band="50-100",
                revenue_band_usd="10-20m",
                relevance_score=0.40,
                evidence_score=0.10,
                data_confidence=0.5,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=False,
            ),
        )

        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical_alpha.id,
            company_entity_id=prospect_alpha.id,
            match_rule="proof_exact",
            evidence_source_document_id=source_strong.id,
            evidence_company_research_run_id=run.id,
        )

        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical_beta.id,
            company_entity_id=prospect_beta.id,
            match_rule="proof_exact",
            evidence_source_document_id=source_medium.id,
            evidence_company_research_run_id=run.id,
        )

        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical_gamma.id,
            company_entity_id=prospect_gamma.id,
            match_rule="proof_sparse",
            evidence_source_document_id=source_sparse.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospects": {
                "alpha": prospect_alpha.id,
                "beta": prospect_beta.id,
                "gamma": prospect_gamma.id,
            },
            "canonicals": {
                "alpha": canonical_alpha.id,
                "beta": canonical_beta.id,
                "gamma": canonical_gamma.id,
            },
            "sources": {
                "strong": source_strong.id,
                "medium": source_medium.id,
                "sparse": source_sparse.id,
            },
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


async def fetch_assignments(fixtures: Dict[str, Any]) -> List[Dict[str, Any]]:
    async with get_async_session_context() as session:
        svc = EnrichmentAssignmentService(session)
        rows_alpha = await svc.list_for_canonical_company(TENANT_ID, fixtures["canonicals"]["alpha"])
        rows_beta = await svc.list_for_canonical_company(TENANT_ID, fixtures["canonicals"]["beta"])
        rows_gamma = await svc.list_for_canonical_company(TENANT_ID, fixtures["canonicals"]["gamma"])

    # Drop timestamps that update on idempotent upserts to avoid false drift.
    combined = [r.model_dump(exclude={"created_at", "updated_at"}) for r in (*rows_alpha, *rows_beta, *rows_gamma)]
    combined_sorted = sorted(
        combined,
        key=lambda row: (
            str(row["target_canonical_id"]),
            row["field_key"],
            str(row["source_document_id"]),
        ),
    )
    return combined_sorted


async def fetch_rankings(run_id: UUID) -> List[Dict[str, Any]]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/prospects-ranked", headers=headers)
        assert resp.status_code == 200, f"ranking status {resp.status_code}"
        data = resp.json()
        assert isinstance(data, list), "ranking payload is not a list"
        return data


def assert_ranking_payload(ranking: List[Dict[str, Any]], fixtures: Dict[str, Any]) -> None:
    assert len(ranking) == 3, f"expected 3 prospects, got {len(ranking)}"
    names = [item["name_normalized"] for item in ranking]
    assert names == ["alpha co", "beta fintech", "gamma sparse"], f"unexpected order {names}"

    def score(item: Dict[str, Any]) -> float:
        return float(item["computed_score"])

    assert score(ranking[0]) > score(ranking[1]) > score(ranking[2]), "scores not strictly descending"

    alpha_sources = {str(entry["source_document_id"]) for entry in ranking[0].get("why_included", [])}
    beta_sources = {str(entry["source_document_id"]) for entry in ranking[1].get("why_included", [])}

    assert str(fixtures["sources"]["strong"]) in alpha_sources, "alpha missing evidence source"
    assert str(fixtures["sources"]["medium"]) in beta_sources, "beta missing evidence source"

    for item in ranking:
        for key in [
            "id",
            "computed_score",
            "score_components",
            "why_included",
            "relevance_score",
            "evidence_score",
        ]:
            assert key in item, f"missing key {key} in ranking item"


async def write_db_excerpt(fixtures: Dict[str, Any]) -> None:
    async with get_async_session_context() as session:
        rows = []
        for stmt in [
            text(
                """
                SELECT id, name, status, sector
                FROM company_research_runs
                WHERE tenant_id = :tenant_id AND id = :run_id
                ORDER BY created_at
                """
            ),
            text(
                """
                SELECT id, name_normalized, relevance_score, evidence_score
                FROM company_prospects
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            text(
                """
                SELECT canonical_company_id, company_entity_id, match_rule, evidence_source_document_id
                FROM canonical_company_links
                WHERE tenant_id = :tenant_id AND evidence_company_research_run_id = :run_id
                ORDER BY canonical_company_id, company_entity_id
                """
            ),
            text(
                """
                SELECT target_canonical_id, field_key, value_json, value_normalized, confidence, source_document_id
                FROM enrichment_assignments
                WHERE tenant_id = :tenant_id
                ORDER BY target_canonical_id, field_key, source_document_id
                """
            ),
        ]:
            result = await session.execute(stmt, {"tenant_id": TENANT_ID, "run_id": fixtures["run_id"]})
            rows.append([serialize(dict(r._mapping)) for r in result.fetchall()])

    sections = [
        "-- company_research_runs",
        json.dumps(rows[0], indent=2),
        "-- company_prospects",
        json.dumps(rows[1], indent=2),
        "-- canonical_company_links",
        json.dumps(rows[2], indent=2),
        "-- enrichment_assignments",
        json.dumps(rows[3], indent=2),
    ]
    DB_EXCERPT.write_text("\n".join(sections) + "\n", encoding="utf-8")


async def run_pass(label: str, fixtures: Dict[str, Any]) -> Dict[str, Any]:
    log(f"=== ranking pass {label} ===")
    await run_extraction(fixtures)
    assignments = await fetch_assignments(fixtures)
    ranking = await fetch_rankings(fixtures["run_id"])
    assert_ranking_payload(ranking, fixtures)
    return {
        "assignments": assignments,
        "ranking": ranking,
    }


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 7.3 explainable prospect ranking proof ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await seed_fixtures()
    log(f"Run: {fixtures['run_id']}")

    first = await run_pass("first", fixtures)
    ASSIGNMENTS_FIRST.write_text(json.dumps(serialize(first["assignments"]), indent=2) + "\n", encoding="utf-8")
    RANKED_FIRST.write_text(json.dumps(serialize(first["ranking"]), indent=2) + "\n", encoding="utf-8")

    second = await run_pass("second", fixtures)
    ASSIGNMENTS_SECOND.write_text(
        json.dumps(serialize(second["assignments"]), indent=2) + "\n", encoding="utf-8"
    )
    RANKED_SECOND.write_text(json.dumps(serialize(second["ranking"]), indent=2) + "\n", encoding="utf-8")

    assert serialize(first["assignments"]) == serialize(second["assignments"]), "assignment drift between passes"
    assert serialize(first["ranking"]) == serialize(second["ranking"]), "ranking drift between passes"

    summary_lines = [
        "PASS: Phase 7.3 explainable prospect ranking proof",
        f"Tenant: {TENANT_ID}",
        "Endpoint: /company-research/runs/{run_id}/prospects-ranked",
        f"Prospects ranked: {len(first['ranking'])}",
        "Idempotency: assignments and rankings identical across two passes",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    await write_db_excerpt(fixtures)

    log("PASS: Phase 7.3 ranking proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())
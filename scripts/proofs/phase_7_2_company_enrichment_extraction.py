"""Phase 7.2 deterministic company enrichment extraction proof.

Creates a research run with two text sources, runs the Stage 7.2 extractor,
asserts evidence-backed assignments, and verifies idempotency across two
passes. Captures console, summary, DB excerpts, and assignment snapshots.
"""

import asyncio
import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_2_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_2_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_2_db_excerpt.sql.txt"
ASSIGNMENTS_FIRST = ARTIFACT_DIR / "phase_7_2_assignments_after_first.json"
ASSIGNMENTS_SECOND = ARTIFACT_DIR / "phase_7_2_assignments_after_second.json"

TENANT_ID = str(uuid.uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
FIXTURES: Dict[str, Any] = {}

SOURCE_ONE_TEXT = (
    "Headquarters: Romania. The company is listed on NASDAQ with ticker ROE. "
    "It delivers renewable energy solutions including solar farms, battery storage, energy storage, and grid services. "
    "Renewable energy platforms and solar projects drive growth."
)

SOURCE_TWO_TEXT = (
    "Based in India, the group is a privately held subsidiary of Tech Holdings. "
    "It focuses on fintech infrastructure, payments processing, and cloud platforms for banks. "
    "The fintech stack and payments network power clients."
)


from app.db.session import get_async_session_context  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate, SourceDocumentCreate  # noqa: E402
from app.services.company_enrichment_extraction_service import CompanyEnrichmentExtractionService  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.services.enrichment_assignment_service import EnrichmentAssignmentService  # noqa: E402


def log(line: str) -> None:
    print(line)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def serialize(data: Any) -> Any:
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, UUID):
        return str(data)
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, list):
        return [serialize(i) for i in data]
    if isinstance(data, dict):
        return {k: serialize(v) for k, v in data.items()}
    return data


def serialize_assignments(rows: List[dict]) -> List[dict]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            row["field_key"],
            str(row["source_document_id"]),
            row["content_hash"],
        ),
    )
    return [serialize(r) for r in sorted_rows]


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        research_service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await research_service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name="phase_7_2_enrichment_run",
                description="Phase 7.2 deterministic extraction proof",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        source_one = await research_service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.2 source one",
                content_text=SOURCE_ONE_TEXT,
                meta={"stage": "7.2", "kind": "proof", "field": "hq_ownership_keywords_1"},
            ),
        )

        source_two = await research_service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.2 source two",
                content_text=SOURCE_TWO_TEXT,
                meta={"stage": "7.2", "kind": "proof", "field": "hq_ownership_keywords_2"},
            ),
        )

        canonical_company = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_7_2_proof_co",
            primary_domain="phase72-proof.example.com",
            country_code="US",
        )

        await session.commit()

        return {
            "run_id": run.id,
            "source_one_id": source_one.id,
            "source_two_id": source_two.id,
            "canonical_company_id": canonical_company.id,
        }


async def fetch_assignments_state() -> Dict[str, List[Dict[str, Any]]]:
    async with get_async_session_context() as session:
        svc = EnrichmentAssignmentService(session)
        company_rows = await svc.list_for_canonical_company(TENANT_ID, FIXTURES["canonical_company_id"])
        return {
            "company": [row.model_dump() for row in company_rows],
        }


def assert_expected_assignments(assignments: List[Dict[str, Any]]) -> None:
    expected = {
        ("hq_country", str(FIXTURES["source_one_id"])): {
            "value": "Romania",
            "confidence": 0.90,
        },
        ("ownership_signal", str(FIXTURES["source_one_id"])): {
            "value": "public_company",
            "confidence": 0.80,
        },
        ("industry_keywords", str(FIXTURES["source_one_id"])): {
            "value": ["renewable energy", "solar", "battery", "energy storage", "grid"],
            "confidence": 0.70,
        },
        ("hq_country", str(FIXTURES["source_two_id"])): {
            "value": "India",
            "confidence": 0.70,
        },
        ("ownership_signal", str(FIXTURES["source_two_id"])): {
            "value": "subsidiary",
            "confidence": 0.80,
        },
        ("industry_keywords", str(FIXTURES["source_two_id"])): {
            "value": ["fintech", "payments", "cloud", "infrastructure"],
            "confidence": 0.70,
        },
    }

    assert len(assignments) == len(expected), f"Unexpected assignment count: {len(assignments)}"  # noqa: EM101

    for assignment in assignments:
        key = (assignment["field_key"], str(assignment["source_document_id"]))
        assert key in expected, f"Unexpected assignment key {key}"
        exp = expected[key]
        assert serialize(assignment["value"]) == exp["value"], f"Value mismatch for {key}"
        assert abs(float(assignment["confidence"]) - exp["confidence"]) < 1e-6, f"Confidence mismatch for {key}"
        assert assignment["target_entity_type"] == "company"
        assert str(assignment["target_canonical_id"]) == str(FIXTURES["canonical_company_id"])
        assert assignment["derived_by"] == "company_enrichment_extraction_v7_2"
        assert assignment["source_document_id"] in {FIXTURES["source_one_id"], FIXTURES["source_two_id"]}


async def write_db_excerpt() -> None:
    async with get_async_session_context() as session:
        db_rows = await session.execute(
            text(
                """
                SELECT id, tenant_id, target_entity_type, target_canonical_id, field_key,
                       value_json, value_normalized, confidence, derived_by, source_document_id,
                       input_scope_hash, content_hash
                FROM enrichment_assignments
                WHERE tenant_id = :tenant_id
                ORDER BY target_entity_type, field_key, source_document_id
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        db_rows = [serialize(dict(row._mapping)) for row in db_rows.fetchall()]

    db_lines = [
        "SELECT * FROM enrichment_assignments WHERE tenant_id = '{tenant}' ORDER BY target_entity_type, field_key, source_document_id;".format(
            tenant=TENANT_ID
        ),
        json.dumps(db_rows, indent=2),
    ]
    DB_EXCERPT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")


async def run_extraction_pass(pass_label: str) -> Dict[str, List[Dict[str, Any]]]:
    log(f"=== Extraction pass {pass_label} ===")
    async with get_async_session_context() as session:
        extractor = CompanyEnrichmentExtractionService(session)
        await extractor.extract_company_enrichment(
            tenant_id=TENANT_ID,
            canonical_company_id=FIXTURES["canonical_company_id"],
            source_document_id=FIXTURES["source_one_id"],
        )
        await extractor.extract_company_enrichment(
            tenant_id=TENANT_ID,
            canonical_company_id=FIXTURES["canonical_company_id"],
            source_document_id=FIXTURES["source_two_id"],
        )

    state = await fetch_assignments_state()
    assert_expected_assignments(state["company"])
    return state


async def main_async() -> None:
    global FIXTURES
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for artifact in [PROOF_CONSOLE, PROOF_SUMMARY, DB_EXCERPT, ASSIGNMENTS_FIRST, ASSIGNMENTS_SECOND]:
        artifact.unlink(missing_ok=True)

    log("=== Phase 7.2 company enrichment extraction proof ===")
    log(f"Tenant: {TENANT_ID}")

    FIXTURES = await seed_fixtures()
    log(f"Run: {FIXTURES['run_id']}")
    log(f"Source one: {FIXTURES['source_one_id']}")
    log(f"Source two: {FIXTURES['source_two_id']}")
    log(f"Canonical company: {FIXTURES['canonical_company_id']}")

    first_state = await run_extraction_pass("first")
    ASSIGNMENTS_FIRST.write_text(json.dumps(serialize_assignments(first_state["company"]), indent=2) + "\n", encoding="utf-8")

    second_state = await run_extraction_pass("second")
    ASSIGNMENTS_SECOND.write_text(json.dumps(serialize_assignments(second_state["company"]), indent=2) + "\n", encoding="utf-8")

    assert len(first_state["company"]) == len(second_state["company"]) == 6

    # Content hashes must be stable per assignment key (field_key + source_document_id).
    def keyed_map(rows: List[Dict[str, Any]]):
        return {
            (row["field_key"], str(row["source_document_id"])): row["content_hash"]
            for row in rows
        }

    first_map = keyed_map(first_state["company"])
    second_map = keyed_map(second_state["company"])
    assert first_map == second_map, "Content hash drift detected"

    summary_lines = [
        "PASS: Phase 7.2 company enrichment extraction proof",
        f"Tenant: {TENANT_ID}",
        f"Assignments after first pass: {len(first_state['company'])}",
        "Idempotency: second pass produced identical content hashes",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    await write_db_excerpt()

    log("PASS: Phase 7.2 extraction proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())
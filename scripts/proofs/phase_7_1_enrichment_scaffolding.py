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
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_1_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_1_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_1_db_excerpt.sql.txt"
ASSIGNMENTS_FIRST = ARTIFACT_DIR / "phase_7_1_assignments_after_first.json"
ASSIGNMENTS_SECOND = ARTIFACT_DIR / "phase_7_1_assignments_after_second.json"

TENANT_ID = str(uuid.uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
FIXTURES: Dict[str, Any] = {}

from app.db.session import get_async_session_context  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate, SourceDocumentCreate  # noqa: E402
from app.schemas.enrichment_assignment import EnrichmentAssignmentCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.services.enrichment_assignment_service import EnrichmentAssignmentService  # noqa: E402


def log(line: str) -> None:
    print(line)


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


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name="phase_7_1_enrichment_run",
                description="Phase 7.1 enrichment proof",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        source = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Phase 7.1 proof source",
                content_text="Phase 7.1 enrichment evidence text for deterministic proof",
                meta={"stage": "7.1", "kind": "proof", "field": "enrichment"},
            ),
        )

        canonical_company = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_7_1_proof_co",
            primary_domain="phase71-proof.example.com",
            country_code="US",
        )

        canonical_person = await repo.create_canonical_person(
            tenant_id=TENANT_ID,
            canonical_full_name="Proof Person 7.1",
            primary_email="proof71@example.com",
            primary_linkedin_url="https://linkedin.com/in/proof71",
        )

        await session.commit()

        return {
            "run_id": run.id,
            "source_id": source.id,
            "canonical_company_id": canonical_company.id,
            "canonical_person_id": canonical_person.id,
        }


async def fetch_assignments_state() -> Dict[str, List[Dict[str, Any]]]:
    async with get_async_session_context() as session:
        svc = EnrichmentAssignmentService(session)
        company_rows = await svc.list_for_canonical_company(TENANT_ID, FIXTURES["canonical_company_id"])
        person_rows = await svc.list_for_canonical_person(TENANT_ID, FIXTURES["canonical_person_id"])
        return {
            "company": [serialize(row.model_dump()) for row in company_rows],
            "person": [serialize(row.model_dump()) for row in person_rows],
        }


def write_db_excerpt(rows: Dict[str, List[Dict[str, Any]]]) -> None:
    db_lines = [
        "SELECT * FROM enrichment_assignments WHERE tenant_id = '{tenant}' ORDER BY target_entity_type, field_key;".format(
            tenant=TENANT_ID
        ),
        json.dumps(rows, indent=2),
    ]
    DB_EXCERPT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")


async def main_async() -> None:
    global FIXTURES
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for artifact in [PROOF_CONSOLE, PROOF_SUMMARY, DB_EXCERPT, ASSIGNMENTS_FIRST, ASSIGNMENTS_SECOND]:
        artifact.unlink(missing_ok=True)

    log("=== Phase 7.1 enrichment scaffolding proof ===")
    log(f"Tenant: {TENANT_ID}")

    FIXTURES = await seed_fixtures()
    log(f"Run: {FIXTURES['run_id']}")
    log(f"Source: {FIXTURES['source_id']}")
    log(f"Canonical company: {FIXTURES['canonical_company_id']}")
    log(f"Canonical person: {FIXTURES['canonical_person_id']}")

    async with get_async_session_context() as session:
        svc = EnrichmentAssignmentService(session)
        first_assignments = await svc.record_assignments(
            tenant_id=TENANT_ID,
            payloads=[
                EnrichmentAssignmentCreate(
                    tenant_id=TENANT_ID,
                    target_entity_type="company",
                    target_canonical_id=FIXTURES["canonical_company_id"],
                    field_key="industry",
                    value="industrial automation",
                    value_normalized="industrial automation",
                    confidence=0.92,
                    derived_by="internal",
                    source_document_id=FIXTURES["source_id"],
                    input_scope_hash="scope_v1",
                ),
                EnrichmentAssignmentCreate(
                    tenant_id=TENANT_ID,
                    target_entity_type="person",
                    target_canonical_id=FIXTURES["canonical_person_id"],
                    field_key="role",
                    value={"title": "Chief Growth Officer", "level": "executive"},
                    value_normalized="chief growth officer",
                    confidence=0.9,
                    derived_by="internal",
                    source_document_id=FIXTURES["source_id"],
                    input_scope_hash="scope_v1",
                ),
            ],
        )
        log(f"First pass assignments: {len(first_assignments)}")

    first_state = await fetch_assignments_state()
    ASSIGNMENTS_FIRST.write_text(json.dumps(first_state, indent=2) + "\n", encoding="utf-8")

    async with get_async_session_context() as session:
        svc = EnrichmentAssignmentService(session)
        second_assignments = await svc.record_assignments(
            tenant_id=TENANT_ID,
            payloads=[
                EnrichmentAssignmentCreate(
                    tenant_id=TENANT_ID,
                    target_entity_type="company",
                    target_canonical_id=FIXTURES["canonical_company_id"],
                    field_key="industry",
                    value="industrial automation",
                    value_normalized="industrial automation",
                    confidence=0.92,
                    derived_by="internal",
                    source_document_id=FIXTURES["source_id"],
                    input_scope_hash="scope_v1",
                ),
                EnrichmentAssignmentCreate(
                    tenant_id=TENANT_ID,
                    target_entity_type="person",
                    target_canonical_id=FIXTURES["canonical_person_id"],
                    field_key="role",
                    value={"title": "Chief Growth Officer", "level": "executive"},
                    value_normalized="chief growth officer",
                    confidence=0.9,
                    derived_by="internal",
                    source_document_id=FIXTURES["source_id"],
                    input_scope_hash="scope_v1",
                ),
            ],
        )
        log(f"Second pass assignments: {len(second_assignments)}")

    second_state = await fetch_assignments_state()
    ASSIGNMENTS_SECOND.write_text(json.dumps(second_state, indent=2) + "\n", encoding="utf-8")

    first_company_count = len(first_state["company"])
    second_company_count = len(second_state["company"])
    first_person_count = len(first_state["person"])
    second_person_count = len(second_state["person"])

    assert first_company_count == second_company_count == 1, "Company assignment count not idempotent"
    assert first_person_count == second_person_count == 1, "Person assignment count not idempotent"

    assert first_state["company"][0]["content_hash"] == second_state["company"][0]["content_hash"]
    assert first_state["person"][0]["content_hash"] == second_state["person"][0]["content_hash"]

    summary_lines = [
        "PASS: Phase 7.1 enrichment scaffolding proof",
        f"Tenant: {TENANT_ID}",
        f"Canonical company assignments: {first_company_count} (rerun delta {second_company_count - first_company_count})",
        f"Canonical person assignments: {first_person_count} (rerun delta {second_person_count - first_person_count})",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    async with get_async_session_context() as session:
        rows = await session.execute(
            text(
                """
                SELECT id, tenant_id, target_entity_type, target_canonical_id, field_key,
                       value_json, value_normalized, confidence, derived_by, source_document_id,
                       input_scope_hash, content_hash
                FROM enrichment_assignments
                WHERE tenant_id = :tenant_id
                ORDER BY target_entity_type, field_key
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        db_rows = [serialize(dict(row._mapping)) for row in rows.fetchall()]
        write_db_excerpt(db_rows)

    log("PASS: Phase 7.1 enrichment proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())

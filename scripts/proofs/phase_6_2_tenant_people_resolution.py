import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

sys.path.append(os.getcwd())

from sqlalchemy import text

from app.db.session import get_async_session_context
from app.models.company_research import ExecutiveProspect, ExecutiveProspectEvidence
from app.schemas.company_research import CompanyResearchRunCreate, CompanyProspectCreate, SourceDocumentCreate
from app.services.company_research_service import CompanyResearchService
from app.workers.company_research_worker import run_worker

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
PROOF_CONSOLE = ARTIFACT_DIR / "phase_6_2_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_6_2_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_6_2_db_excerpt.sql.txt"
CANONICAL_JSON = ARTIFACT_DIR / "phase_6_2_canonical_people.json"
LINKS_JSON = ARTIFACT_DIR / "phase_6_2_links.json"
SOURCES_JSON = ARTIFACT_DIR / "phase_6_2_sources_used.json"

TENANT_ID = "b3909011-8bd3-439d-a421-3b70fae124e9"
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")


def log(line: str) -> None:
    print(line)


def serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "_mapping"):
            payload.append({k: (str(v) if v is not None else None) for k, v in dict(row._mapping).items()})
        elif hasattr(row, "_asdict"):
            payload.append({k: (str(v) if v is not None else None) for k, v in row._asdict().items()})
        elif hasattr(row, "__dict__"):
            payload.append({k: (str(v) if v is not None else None) for k, v in row.__dict__.items() if not k.startswith("_")})
        else:
            payload.append({"value": str(row)})
    return payload


async def create_run_with_exec(email: str, label: str) -> dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=f"phase6_2_{label}_{uuid.uuid4().hex[:6]}",
                description=f"Phase 6.2 proof {label}",
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
                title=f"Proof source {label}",
                content_text=f"Email holder {email} in {label}",
                meta={"kind": "text", "label": label},
            ),
        )

        prospect = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw=f"ProofCo {label}",
                name_normalized=f"proofco {label}",
                sector="demo",
                subsector="proof",
                employees_band="50-100",
                revenue_band_usd="1-5m",
                description=f"Proof company {label}",
                data_confidence=0.8,
                relevance_score=0.9,
                evidence_score=0.8,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=True,
            ),
        )

        exec_row = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run.id,
            company_prospect_id=prospect.id,
            name_raw=f"Pat {label}",
            name_normalized=f"pat {label}",
            title="CEO",
            email=email,
            confidence=0.9,
            status="new",
            source_label="proof_manual",
            source_document_id=source.id,
        )
        session.add(exec_row)
        await session.flush()

        evidence = ExecutiveProspectEvidence(
            tenant_id=TENANT_ID,
            executive_prospect_id=exec_row.id,
            source_type="text",
            source_name=f"Proof evidence {label}",
            source_url=None,
            raw_snippet=f"Evidence for {label}",
            evidence_weight=0.5,
            source_document_id=source.id,
        )
        session.add(evidence)
        await session.flush()

        job = await service.start_run(tenant_id=TENANT_ID, run_id=run.id)

        return {
            "run_id": run.id,
            "job_id": job.id,
            "source_id": source.id,
            "prospect_id": prospect.id,
            "exec_id": exec_row.id,
        }


async def reset_steps_for_rerun(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        steps = await service.list_run_steps(TENANT_ID, run_id)
        for step in steps:
            step.status = "pending"
            step.attempt_count = 0
            step.started_at = None
            step.finished_at = None
            step.next_retry_at = None
            step.output_json = None
            step.last_error = None
        await session.flush()
        await service.retry_run(TENANT_ID, run_id)


async def fetch_canonical_state(email_norm: str) -> dict[str, Any]:
    async with get_async_session_context() as session:
        data: dict[str, Any] = {}

        canonical_rows = await session.execute(
            text(
                """
                SELECT cp.id, cp.tenant_id, cp.canonical_full_name, cp.primary_email, cp.primary_linkedin_url,
                       cp.created_at, cp.updated_at
                FROM canonical_people cp
                JOIN canonical_person_emails cpe ON cpe.canonical_person_id = cp.id
                WHERE cp.tenant_id = :tenant_id AND cpe.email_normalized = :email
                ORDER BY cp.created_at
                """
            ),
            {"tenant_id": TENANT_ID, "email": email_norm},
        )
        data["canonical_people"] = canonical_rows.fetchall()

        email_rows = await session.execute(
            text(
                """
                SELECT id, canonical_person_id, email_normalized
                FROM canonical_person_emails
                WHERE tenant_id = :tenant_id AND email_normalized = :email
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "email": email_norm},
        )
        data["emails"] = email_rows.fetchall()

        link_rows = await session.execute(
            text(
                """
                SELECT cpl.id, cpl.canonical_person_id, cpl.person_entity_id, cpl.match_rule,
                       cpl.evidence_source_document_id, cpl.evidence_company_research_run_id
                FROM canonical_person_links cpl
                JOIN canonical_person_emails cpe ON cpe.canonical_person_id = cpl.canonical_person_id
                WHERE cpl.tenant_id = :tenant_id AND cpe.email_normalized = :email
                ORDER BY cpl.created_at
                """
            ),
            {"tenant_id": TENANT_ID, "email": email_norm},
        )
        data["links"] = link_rows.fetchall()

        source_rows = await session.execute(
            text(
                """
                SELECT id, company_research_run_id, source_type, title
                FROM source_documents
                WHERE tenant_id = :tenant_id
                ORDER BY created_at DESC
                LIMIT 10
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        data["sources"] = source_rows.fetchall()

        counts = await session.execute(
            text(
                """
                SELECT
                                    (SELECT count(*) FROM canonical_people cp JOIN canonical_person_emails cpe ON cp.id = cpe.canonical_person_id WHERE cp.tenant_id = :tenant_id AND cpe.email_normalized = :email) AS people_count,
                                    (SELECT count(*) FROM canonical_person_links cpl JOIN canonical_person_emails cpe ON cpl.canonical_person_id = cpe.canonical_person_id WHERE cpl.tenant_id = :tenant_id AND cpe.email_normalized = :email) AS link_count
                """
            ),
                        {"tenant_id": TENANT_ID, "email": email_norm},
        )
        data["counts"] = counts.fetchone()

        return data


async def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_SUMMARY.unlink(missing_ok=True)
    DB_EXCERPT.unlink(missing_ok=True)
    CANONICAL_JSON.unlink(missing_ok=True)
    LINKS_JSON.unlink(missing_ok=True)
    SOURCES_JSON.unlink(missing_ok=True)

    shared_email = f"phase6_2_{uuid.uuid4().hex[:8]}@example.com"
    shared_email_norm = shared_email.strip().lower()

    log(f"Shared email: {shared_email}")

    run_a = await create_run_with_exec(shared_email, "A")
    run_b = await create_run_with_exec(shared_email, "B")

    log(f"Run A {run_a['run_id']}, Run B {run_b['run_id']}")

    await run_worker(loop=False, sleep_seconds=1)
    await run_worker(loop=False, sleep_seconds=1)

    first_state = await fetch_canonical_state(shared_email_norm)

    people_count_first = first_state["counts"].people_count if first_state.get("counts") else 0
    link_count_first = first_state["counts"].link_count if first_state.get("counts") else 0

    assert len(first_state["canonical_people"]) == 1, "Expected exactly one canonical person for shared email"
    assert people_count_first >= 1, "Expected at least one canonical person after first pass"
    assert link_count_first >= 2, "Expected at least two links after first pass (two runs)"

    # Validate evidence is present per link
    allowed_sources = {run_a["source_id"], run_b["source_id"]}
    allowed_sources_str = {str(s) for s in allowed_sources}
    for row in first_state["links"]:
        assert row.evidence_source_document_id, "Link missing evidence_source_document_id"
        assert str(row.evidence_source_document_id) in allowed_sources_str, "Link evidence source not in expected set"

    # Idempotency pass: reset steps for both runs, rerun worker twice
    await reset_steps_for_rerun(run_a["run_id"])
    await reset_steps_for_rerun(run_b["run_id"])
    await run_worker(loop=False, sleep_seconds=1)
    await run_worker(loop=False, sleep_seconds=1)

    second_state = await fetch_canonical_state(shared_email_norm)
    people_count_second = second_state["counts"].people_count if second_state.get("counts") else 0
    link_count_second = second_state["counts"].link_count if second_state.get("counts") else 0

    assert people_count_second == people_count_first, "Canonical people count changed on rerun"
    assert link_count_second == link_count_first, "Canonical person links count changed on rerun"

    summary_lines = [
        "PASS: Phase 6.2 tenant-wide canonical people resolution",
        f"Tenant: {TENANT_ID}",
        f"Run A: {run_a['run_id']}",
        f"Run B: {run_b['run_id']}",
        f"Shared email: {shared_email_norm}",
        f"Canonical people count: {people_count_first} (rerun delta {people_count_second - people_count_first})",
        f"Canonical person links: {link_count_first} (rerun delta {link_count_second - link_count_first})",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    CANONICAL_JSON.write_text(json.dumps(serialize_rows(first_state["canonical_people"]), indent=2) + "\n", encoding="utf-8")
    LINKS_JSON.write_text(json.dumps(serialize_rows(first_state["links"]), indent=2) + "\n", encoding="utf-8")
    SOURCES_JSON.write_text(json.dumps(serialize_rows(first_state["sources"]), indent=2) + "\n", encoding="utf-8")

    db_lines = [
        "SELECT cp.id, cp.canonical_full_name, cp.primary_email, cp.primary_linkedin_url FROM canonical_people cp WHERE tenant_id = '{tenant}';".format(tenant=TENANT_ID),
        json.dumps(serialize_rows(first_state["canonical_people"]), indent=2),
        "",
        "SELECT id, canonical_person_id, email_normalized FROM canonical_person_emails WHERE tenant_id = '{tenant}';".format(tenant=TENANT_ID),
        json.dumps(serialize_rows(first_state["emails"]), indent=2),
        "",
        "SELECT id, canonical_person_id, person_entity_id, match_rule, evidence_source_document_id, evidence_company_research_run_id FROM canonical_person_links WHERE tenant_id = '{tenant}';".format(tenant=TENANT_ID),
        json.dumps(serialize_rows(first_state["links"]), indent=2),
    ]
    DB_EXCERPT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")

    log("PASS: Phase 6.2 proof complete")


if __name__ == "__main__":
    asyncio.run(main())

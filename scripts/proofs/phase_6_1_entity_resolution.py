import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.append(os.getcwd())

from sqlalchemy import text

from app.db.session import get_async_session_context
from app.models.company_research import CompanyProspect, ExecutiveProspect, ExecutiveProspectEvidence
from app.schemas.company_research import CompanyResearchRunCreate, CompanyProspectCreate, SourceDocumentCreate
from app.services.company_research_service import CompanyResearchService
from app.services.entity_resolution_service import EntityResolutionService
from app.workers.company_research_worker import run_worker

TENANT_ID = "b3909011-8bd3-439d-a421-3b70fae124e9"
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
PROOF_ARTIFACT = ARTIFACT_DIR / "phase_6_1_proof_2.txt"
DB_ARTIFACT = ARTIFACT_DIR / "phase_6_1_db_excerpt_2.sql.txt"


def log(line: str) -> None:
    print(line)


def serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    payload = []
    for row in rows:
        if hasattr(row, "_mapping"):
            payload.append({k: str(v) for k, v in dict(row._mapping).items()})
        elif hasattr(row, "_asdict"):
            payload.append({k: str(v) for k, v in row._asdict().items()})
        elif hasattr(row, "__dict__"):
            payload.append({k: str(v) for k, v in row.__dict__.items() if not k.startswith("_")})
        else:
            payload.append({"value": str(row)})
    return payload


async def seed_run() -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        run_name = f"stage6_1_proof_{uuid.uuid4().hex[:8]}"
        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=run_name,
                description="Stage 6.1 proof run",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        source_one = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Exec source A",
                content_text="Proof source A",
                meta={"kind": "text", "submitted_via": "proof"},
            ),
        )
        source_two = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Exec source B",
                content_text="Proof source B",
                meta={"kind": "text", "submitted_via": "proof"},
            ),
        )

        prospect = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="ProofCo Holdings",
                name_normalized="proofco holdings",
                sector="demo",
                subsector="proof",
                employees_band="50-100",
                revenue_band_usd="1-5m",
                description="Proof company for Stage 6.1",
                data_confidence=0.8,
                relevance_score=0.9,
                evidence_score=0.8,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=True,
            ),
        )

        exec_one = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run.id,
            company_prospect_id=prospect.id,
            name_raw="Pat Proof",
            name_normalized="pat proof",
            title="CEO",
            email="proof.ceo@example.com",
            confidence=0.9,
            status="new",
            source_label="proof_manual",
            source_document_id=source_one.id,
        )
        exec_two = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run.id,
            company_prospect_id=prospect.id,
            name_raw="Patrick Proof",
            name_normalized="patrick proof",
            title="Chief Executive Officer",
            email="proof.ceo@example.com",
            confidence=0.85,
            status="new",
            source_label="proof_manual",
            source_document_id=source_two.id,
        )
        session.add_all([exec_one, exec_two])
        await session.flush()

        evidence = ExecutiveProspectEvidence(
            tenant_id=TENANT_ID,
            executive_prospect_id=exec_two.id,
            source_type="text",
            source_name="Exec article",
            source_url=None,
            raw_snippet="Evidence for duplicate exec",
            evidence_weight=0.5,
            source_document_id=source_two.id,
        )
        session.add(evidence)
        await session.flush()

        job = await service.start_run(tenant_id=TENANT_ID, run_id=run.id)

        return {
            "run_id": run.id,
            "job_id": job.id,
            "sources": [source_one.id, source_two.id],
            "prospect_id": prospect.id,
            "executives": [exec_one.id, exec_two.id],
        }


async def reset_steps_for_rerun(tenant_id: str, run_id: UUID) -> None:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        steps = await service.list_run_steps(tenant_id, run_id)
        for step in steps:
            if step.step_key in {"process_sources", "entity_resolution"}:
                step.status = "pending"
                step.attempt_count = 0
                step.started_at = None
                step.finished_at = None
                step.next_retry_at = None
                step.output_json = None
                step.last_error = None
        await session.flush()
        await service.retry_run(tenant_id, run_id)


async def fetch_resolution_state(tenant_id: str, run_id: UUID) -> dict[str, Any]:
    async with get_async_session_context() as session:
        resolver = EntityResolutionService(session)
        resolved = await resolver.list_resolved_entities(tenant_id, run_id, entity_type="executive")
        links = await resolver.list_entity_merge_links(tenant_id, run_id, entity_type="executive")

        events_service = CompanyResearchService(session)
        events = await events_service.list_events_for_run(tenant_id, run_id, limit=50)
        resolution_events = [e for e in events if e.event_type == "entity_resolution"]

        rows = await session.execute(
            text(
                """
                SELECT id, canonical_entity_id, evidence_source_document_ids, resolution_hash
                FROM resolved_entities
                WHERE company_research_run_id = :run_id
                ORDER BY canonical_entity_id
                """
            ),
            {"run_id": str(run_id)},
        )
        resolved_rows = rows.fetchall()

        link_rows = await session.execute(
            text(
                """
                SELECT id, canonical_entity_id, duplicate_entity_id, evidence_source_document_ids, resolution_hash
                FROM entity_merge_links
                WHERE company_research_run_id = :run_id
                ORDER BY canonical_entity_id, duplicate_entity_id
                """
            ),
            {"run_id": str(run_id)},
        )
        merge_rows = link_rows.fetchall()

        return {
            "resolved": resolved,
            "links": links,
            "events": resolution_events,
            "resolved_rows": resolved_rows,
            "merge_rows": merge_rows,
        }


async def main() -> None:
    PROOF_ARTIFACT.unlink(missing_ok=True)
    DB_ARTIFACT.unlink(missing_ok=True)

    seed = await seed_run()
    run_id = seed["run_id"]

    log(f"Seeded run {run_id} with sources {seed['sources']} and execs {seed['executives']}")

    await run_worker(loop=False, sleep_seconds=1)
    first_state = await fetch_resolution_state(TENANT_ID, run_id)

    resolved_first = len(first_state["resolved"])
    links_first = len(first_state["links"])
    log(f"First pass: resolved={resolved_first}, links={links_first}")

    assert resolved_first >= 1, "Expected at least one resolved entity after first pass"
    assert links_first >= 1, "Expected at least one merge link after first pass"

    # Rerun the same steps to prove idempotency
    await reset_steps_for_rerun(TENANT_ID, run_id)
    await run_worker(loop=False, sleep_seconds=1)
    second_state = await fetch_resolution_state(TENANT_ID, run_id)

    resolved_second = len(second_state["resolved"])
    links_second = len(second_state["links"])
    log(f"Second pass: resolved={resolved_second}, links={links_second}")

    assert resolved_second == resolved_first, "Resolved entity count changed on rerun"
    assert links_second == links_first, "Merge link count changed on rerun"

    # Evidence check
    evidence_lists = [link.evidence_source_document_ids for link in second_state["links"]]
    flattened_evidence = {item for sublist in evidence_lists for item in sublist}
    assert flattened_evidence, "Merge links missing evidence source document IDs"

    # Event check
    assert second_state["events"], "Missing entity_resolution event records"

    summary_lines = [
        "PASS: Stage 6.1 entity resolution end-to-end",
        f"Run ID: {run_id}",
        f"Resolved entities: {resolved_first} (rerun delta {resolved_second - resolved_first})",
        f"Merge links: {links_first} (rerun delta {links_second - links_first})",
        f"Evidence source documents referenced: {sorted(flattened_evidence)}",
    ]
    PROOF_ARTIFACT.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    db_lines = [
        "SELECT id, canonical_entity_id, evidence_source_document_ids, resolution_hash FROM resolved_entities ORDER BY canonical_entity_id;",
        json.dumps(serialize_rows(first_state["resolved_rows"]), indent=2),
        "",
        "SELECT id, canonical_entity_id, duplicate_entity_id, evidence_source_document_ids, resolution_hash FROM entity_merge_links ORDER BY canonical_entity_id, duplicate_entity_id;",
        json.dumps(serialize_rows(first_state["merge_rows"]), indent=2),
    ]
    DB_ARTIFACT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")

    log("PASS: Stage 6.1 proof complete")


if __name__ == "__main__":
    asyncio.run(main())

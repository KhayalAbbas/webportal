"""Phase 8.2 proof: ATS wiring for accepted executives.

Creates a real role/mandate, seeds a company research run with executives,
patches review_status to accepted, promotes an executive into ATS with
role/stage/evidence, asserts idempotency, captures DB excerpts and OpenAPI,
and writes deterministic artifacts under scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.schemas.company import CompanyCreate  # noqa: E402
from app.schemas.company_research import (  # noqa: E402
    CompanyProspectCreate,
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from app.schemas.role import RoleCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.services.company_service import CompanyService  # noqa: E402
from app.services.role_service import RoleService  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_8_2_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_8_2_proof.txt"
FIRST_CALL = ARTIFACT_DIR / "phase_8_2_first_call.json"
SECOND_CALL = ARTIFACT_DIR / "phase_8_2_second_call.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_8_2_db_excerpt.sql.txt"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_8_2_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_8_2_openapi_after_excerpt.txt"

TENANT_ID = str(uuid4())
RUN_NAME = "phase_8_2_ats_wiring"
ROLE_TITLE = "VP Engineering"
STAGE_CODE = "SOURCED"
STAGE_NAME = "Sourced"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.email = "proof@example.com"
        self.username = "proof"
        self.id = UUID(int=0)


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


app.dependency_overrides[verify_user_tenant_access] = override_verify_user


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
        FIRST_CALL,
        SECOND_CALL,
        DB_EXCERPT,
        OPENAPI_AFTER,
        OPENAPI_AFTER_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


async def ensure_pipeline_stage(session) -> PipelineStage:
    existing = await session.execute(
        select(PipelineStage).where(PipelineStage.tenant_id == TENANT_ID).order_by(PipelineStage.order_index.asc())
    )
    stage = existing.scalars().first()
    if stage:
        return stage

    stage = PipelineStage(
        id=uuid4(),
        tenant_id=TENANT_ID,
        code=STAGE_CODE,
        name=STAGE_NAME,
        order_index=1,
    )
    session.add(stage)
    await session.flush()
    await session.refresh(stage)
    return stage


async def seed_foundation() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        company_service = CompanyService(session)
        role_service = RoleService(session)
        research_service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        company = await company_service.create_company(
            TENANT_ID,
            CompanyCreate(
                tenant_id=TENANT_ID,
                name="Phase 8.2 Proof Co",
                industry="software",
                headquarters_location="Remote",
                website="https://phase-82.example.com",
                is_client=True,
                is_prospect=True,
            ),
        )

        role = await role_service.create_role(
            TENANT_ID,
            RoleCreate(
                tenant_id=TENANT_ID,
                company_id=company.id,
                title=ROLE_TITLE,
                function="Engineering",
                location="Remote",
                status="open",
                seniority_level="Executive",
                description="Phase 8.2 ATS wiring proof role",
            ),
        )

        stage = await ensure_pipeline_stage(session)

        run = await research_service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=role.id,
                name=RUN_NAME,
                description="Phase 8.2 ATS wiring proof",
                sector="software",
                region_scope=["US"],
                status="active",
            ),
        )

        seed_source = await research_service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="phase_8_2_seed",
                content_text="seed for phase 8.2 ats wiring",
                meta={"label": "phase_8_2"},
            ),
        )

        company_prospect = await research_service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=role.id,
                name_raw="Phase 8.2 Prospect",
                name_normalized="phase 8.2 prospect",
                website_url="https://phase-82.example.com",
                hq_country="US",
                sector="software",
                subsector="automation",
                relevance_score=0.9,
                evidence_score=0.9,
                status="accepted",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )

        canonical = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="phase_8_2_proof",
            primary_domain="phase-82.example.com",
            country_code="US",
        )
        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical.id,
            company_entity_id=company_prospect.id,
            match_rule="phase_8_2_proof_seed",
            evidence_source_document_id=seed_source.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "company": company,
            "role": role,
            "stage": stage,
            "run": run,
            "prospect": company_prospect,
            "seed_source": seed_source,
            "canonical_company": canonical,
        }


async def run_internal_discovery(run_id: UUID) -> dict:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        result = await service.run_internal_executive_discovery(
            tenant_id=TENANT_ID,
            run_id=run_id,
            provider="internal_stub",
            model_name="phase_8_2_internal_stub",
        )
        await session.commit()
        return result


async def pick_executive(run_id: UUID) -> UUID:
    async with get_async_session_context() as session:
        repo = CompanyResearchRepository(session)
        execs = await repo.list_executive_prospects_for_run(TENANT_ID, run_id)
        assert execs, "no executives discovered"
        exec_ids = sorted([e.id for e in execs], key=lambda v: str(v))
        return exec_ids[0]


async def patch_review_status(client: AsyncClient, executive_id: UUID, status: str) -> dict:
    resp = await client.patch(
        f"/company-research/executives/{executive_id}/review-status",
        headers={"X-Tenant-ID": TENANT_ID},
        json={"review_status": status},
    )
    assert resp.status_code == 200, f"review patch {status} failed: {resp.status_code} {resp.text}"
    return resp.json()


async def post_pipeline(
    client: AsyncClient,
    executive_id: UUID,
    *,
    role_id: UUID,
    stage_id: Optional[UUID],
) -> dict:
    resp = await client.post(
        f"/company-research/executives/{executive_id}/pipeline",
        headers={"X-Tenant-ID": TENANT_ID},
        json={
            "assignment_status": "sourced",
            "current_stage_id": str(stage_id) if stage_id else None,
            "role_id": str(role_id),
            "notes": "phase 8.2 proof",
        },
    )
    assert resp.status_code == 200, f"pipeline post failed: {resp.status_code} {resp.text}"
    return resp.json()


async def count_rows() -> Dict[str, int]:
    async with get_async_session_context() as session:
        async def table_count(model) -> int:
            result = await session.execute(select(func.count()).select_from(model).where(model.tenant_id == TENANT_ID))
            return int(result.scalar_one())

        from app.models.candidate import Candidate  # local import
        from app.models.contact import Contact
        from app.models.candidate_assignment import CandidateAssignment
        from app.models.research_event import ResearchEvent
        from app.models.source_document import SourceDocument
        from app.models.activity_log import ActivityLog

        return {
            "candidate": await table_count(Candidate),
            "contact": await table_count(Contact),
            "assignment": await table_count(CandidateAssignment),
            "research_event": await table_count(ResearchEvent),
            "source_document": await table_count(SourceDocument),
            "activity_log": await table_count(ActivityLog),
        }


async def write_db_excerpt(executive_id: UUID, pipeline_result: dict) -> None:
    candidate_id = pipeline_result.get("candidate_id")
    contact_id = pipeline_result.get("contact_id")
    assignment_id = pipeline_result.get("assignment_id")
    research_event_id = pipeline_result.get("research_event_id")
    source_document_id = pipeline_result.get("source_document_id")

    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, review_status, verification_status, candidate_id, contact_id, candidate_assignment_id, created_at, updated_at
                FROM executive_prospects
                WHERE tenant_id = :tenant_id AND id = :exec_id
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

        activity_rows = await session.execute(
            text(
                """
                SELECT type, message, candidate_id, contact_id, role_id, created_at
                FROM activity_log
                WHERE tenant_id = :tenant_id AND type IN ('EXECUTIVE_REVIEW_STATUS','EXECUTIVE_PIPELINE_CREATE','EXECUTIVE_PIPELINE_STAGE_SET')
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )

        candidate_rows = await session.execute(
            text(
                """
                SELECT id, first_name, last_name, email, current_title, current_company, created_at
                FROM candidate
                WHERE tenant_id = :tenant_id AND id = :candidate_id
                """
            ),
            {"tenant_id": TENANT_ID, "candidate_id": str(candidate_id)},
        )

        contact_rows = None
        if contact_id:
            contact_rows = await session.execute(
                text(
                    """
                    SELECT id, company_id, first_name, last_name, email, role_title, created_at
                    FROM contact
                    WHERE tenant_id = :tenant_id AND id = :contact_id
                    """
                ),
                {"tenant_id": TENANT_ID, "contact_id": str(contact_id)},
            )

        assignment_rows = await session.execute(
            text(
                """
                SELECT a.id, a.candidate_id, a.role_id, a.status, a.current_stage_id, a.source, a.notes, a.created_at, s.code AS stage_code, s.name AS stage_name
                FROM candidate_assignment a
                LEFT JOIN pipeline_stage s ON a.current_stage_id = s.id
                WHERE a.tenant_id = :tenant_id AND a.id = :assignment_id
                """
            ),
            {"tenant_id": TENANT_ID, "assignment_id": str(assignment_id)},
        )

        stage_rows = await session.execute(
            text(
                """
                SELECT id, code, name, order_index, created_at
                FROM pipeline_stage
                WHERE tenant_id = :tenant_id
                ORDER BY order_index ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )

        research_event_rows = await session.execute(
            text(
                """
                SELECT id, source_type, entity_type, entity_id, raw_payload
                FROM research_event
                WHERE tenant_id = :tenant_id AND id = :research_event_id
                """
            ),
            {"tenant_id": TENANT_ID, "research_event_id": str(research_event_id)},
        )

        source_document_rows = await session.execute(
            text(
                """
                SELECT id, research_event_id, document_type, title, url, metadata
                FROM source_document
                WHERE tenant_id = :tenant_id AND id = :source_document_id
                """
            ),
            {"tenant_id": TENANT_ID, "source_document_id": str(source_document_id)},
        )

    def rows_to_list(rows) -> List[Dict[str, Any]]:
        return [dict(r._mapping) for r in rows.fetchall()] if rows else []

    lines = [
        "-- executive_prospect",
        json.dumps(rows_to_list(exec_rows), indent=2, sort_keys=True, default=str),
        "-- activity_log",
        json.dumps(rows_to_list(activity_rows), indent=2, sort_keys=True, default=str),
        "-- candidate",
        json.dumps(rows_to_list(candidate_rows), indent=2, sort_keys=True, default=str),
        "-- contact",
        json.dumps(rows_to_list(contact_rows), indent=2, sort_keys=True, default=str) if contact_rows else "[]",
        "-- candidate_assignment",
        json.dumps(rows_to_list(assignment_rows), indent=2, sort_keys=True, default=str),
        "-- pipeline_stage",
        json.dumps(rows_to_list(stage_rows), indent=2, sort_keys=True, default=str),
        "-- research_event",
        json.dumps(rows_to_list(research_event_rows), indent=2, sort_keys=True, default=str),
        "-- source_document",
        json.dumps(rows_to_list(source_document_rows), indent=2, sort_keys=True, default=str),
    ]

    DB_EXCERPT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def capture_openapi(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json", headers={"X-Tenant-ID": TENANT_ID})
    assert resp.status_code == 200, f"openapi status {resp.status_code}: {resp.text}"
    data = resp.json()
    dump_json(OPENAPI_AFTER, data)

    paths = data.get("paths") or {}
    excerpt = {
        path: body
        for path, body in paths.items()
        if "/executives/" in path and "pipeline" in path
    }
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 8.2 ATS wiring proof ===")
    log(f"Tenant: {TENANT_ID}")

    seed = await seed_foundation()
    log(f"Role: {seed['role'].id}")
    log(f"Run: {seed['run'].id}")

    discovery_stats = await run_internal_discovery(seed["run"].id)
    log(f"Discovery stats: {discovery_stats}")

    exec_id = await pick_executive(seed["run"].id)
    log(f"Executive chosen: {exec_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await patch_review_status(client, exec_id, "accepted")

        first = await post_pipeline(client, exec_id, role_id=seed["role"].id, stage_id=seed["stage"].id)
        dump_json(FIRST_CALL, first)
        log(f"First pipeline call: {first}")

        counts_before = await count_rows()
        log(f"Counts after first call: {counts_before}")

        await write_db_excerpt(exec_id, first)

        second = await post_pipeline(client, exec_id, role_id=seed["role"].id, stage_id=seed["stage"].id)
        dump_json(SECOND_CALL, second)
        log(f"Second pipeline call: {second}")

        assert first == second, "idempotency failure: pipeline responses differ"

        counts_after = await count_rows()
        log(f"Counts after second call: {counts_after}")
        assert counts_after == counts_before, "idempotency failure: counts changed on second call"

        await capture_openapi(client)

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "PHASE 8.2 ATS WIRING PROOF: PASS",
                f"tenant={TENANT_ID}",
                f"role_id={seed['role'].id}",
                f"run_id={seed['run'].id}",
                f"executive_id={exec_id}",
                f"assignment_id={first.get('assignment_id')}",
                f"pipeline_stage_id={first.get('pipeline_stage_id')}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

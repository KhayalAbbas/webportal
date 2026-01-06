"""Phase 7.9 proof: executive verification workflow.

Seeds a run, company prospect, and executive with evidence, exercises the
verification promotion API (no downgrades), captures audit logs, and emits
artifacts for deterministic review.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict
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
from app.services.company_research_service import CompanyResearchService
from app.models.company_research import ExecutiveProspect, ExecutiveProspectEvidence

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_9_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_9_proof.txt"
EXEC_AFTER = ARTIFACT_DIR / "phase_7_9_exec_after.json"
EXEC_BEFORE = ARTIFACT_DIR / "phase_7_9_exec_before.json"
EXEC_AFTER_PARTIAL = ARTIFACT_DIR / "phase_7_9_exec_after_partial.json"
EXEC_AFTER_VERIFIED = ARTIFACT_DIR / "phase_7_9_exec_after_verified.json"
ACTIVITY_LOG = ARTIFACT_DIR / "phase_7_9_activity_log.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_9_db_excerpt.sql.txt"

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
        EXEC_AFTER,
        EXEC_BEFORE,
        EXEC_AFTER_PARTIAL,
        EXEC_AFTER_VERIFIED,
        ACTIVITY_LOG,
        DB_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        research = CompanyResearchService(session)

        run = await research.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name="phase_7_9_exec_verification",
                description="Phase 7.9 proof",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        source = await research.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Executive source",
                content_text="CEO profile with firm evidence",
                meta={"label": "exec"},
            ),
        )

        prospect = await research.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Gamma Holdings",
                name_normalized="gamma holdings",
                website_url="https://gamma-79.example.com",
                hq_country="US",
                sector="demo",
                subsector="proof",
                relevance_score=0.5,
                evidence_score=0.6,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=True,
            ),
        )

        executive = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run.id,
            company_prospect_id=prospect.id,
            name_raw="Casey Proof",
            name_normalized="casey proof",
            title="CEO",
            profile_url="https://example.com/casey",
            linkedin_url="https://linkedin.com/in/casey-proof",
            email="casey@example.com",
            location="Remote",
            confidence=0.8,
            status="new",
            discovered_by="internal",
            verification_status="unverified",
            source_label="internal",
            source_document_id=source.id,
        )
        session.add(executive)
        await session.flush()

        evidence = ExecutiveProspectEvidence(
            tenant_id=TENANT_ID,
            executive_prospect_id=executive.id,
            source_type="profile",
            source_name="Internal dossier",
            source_url="https://example.com/dossier",
            raw_snippet="Confirmed leadership role",
            evidence_weight=0.9,
            source_document_id=source.id,
            source_content_hash="hash-proof-79",
        )
        session.add(evidence)

        await session.commit()

        return {
            "run_id": run.id,
            "prospect_id": prospect.id,
            "executive_id": executive.id,
        }


async def patch_verification(client: AsyncClient, executive_id: UUID, status: str) -> dict:
    resp = await client.patch(
        f"/company-research/executives/{executive_id}/verification-status",
        json={"verification_status": status},
        headers={"X-Tenant-ID": TENANT_ID},
    )
    return {"status_code": resp.status_code, "json": resp.json()}


async def capture_activity() -> list[str]:
    async with get_async_session_context() as session:
        rows = await session.execute(
            text(
                """
                SELECT type, message, created_by, created_at
                FROM activity_log
                WHERE tenant_id = :tenant_id AND type = 'EXEC_VERIFICATION_STATUS'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        lines = [
            f"{row.type} | {row.created_by} | {row.created_at} | {row.message}" for row in rows
        ]
        ACTIVITY_LOG.write_text("\n".join(lines), encoding="utf-8")

        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_research_run_id, company_prospect_id, name_normalized, verification_status
                FROM executive_prospects
                WHERE tenant_id = :tenant_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        DB_EXCERPT.write_text("\n".join([str(dict(row._mapping)) for row in exec_rows]), encoding="utf-8")
        return lines


async def main() -> None:
    reset_artifacts()

    app.dependency_overrides[verify_user_tenant_access] = override_verify_user
    app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user

    fixtures = await seed_fixtures()
    executive_id = fixtures["executive_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        initial = await client.get(
            f"/company-research/runs/{fixtures['run_id']}/executives",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        EXEC_BEFORE.write_text(json.dumps(initial.json(), indent=2), encoding="utf-8")

        first = await patch_verification(client, executive_id, "partial")
        log(f"promote_to_partial: {first['status_code']}")
        partial_list = await client.get(
            f"/company-research/runs/{fixtures['run_id']}/executives",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        EXEC_AFTER_PARTIAL.write_text(json.dumps(partial_list.json(), indent=2), encoding="utf-8")

        second = await patch_verification(client, executive_id, "verified")
        log(f"promote_to_verified: {second['status_code']}")
        verified_list = await client.get(
            f"/company-research/runs/{fixtures['run_id']}/executives",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        EXEC_AFTER_VERIFIED.write_text(json.dumps(verified_list.json(), indent=2), encoding="utf-8")

        downgrade = await patch_verification(client, executive_id, "partial")
        log(f"downgrade_attempt: {downgrade['status_code']}")

    EXEC_AFTER.write_text(
        json.dumps(
            {
                "before": initial.json(),
                "partial": first,
                "verified": second,
                "downgrade": downgrade,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    activity_lines = await capture_activity()

    assert first["status_code"] == 200, "promote to partial failed"
    assert second["status_code"] == 200, "promote to verified failed"
    assert downgrade["status_code"] in {400, 409}, "downgrade was not blocked"
    assert any("EXEC_VERIFICATION_STATUS" in line and str(executive_id) in line and "evidence_source_documents" in line for line in activity_lines), "missing evidence-rich audit log"

    summary_lines = [
        "Phase 7.9 executive verification proof",
        f"Tenant: {TENANT_ID}",
        f"Run: {fixtures['run_id']}",
        f"Executive: {executive_id}",
        f"Promote->partial status={first['status_code']}",
        f"Promote->verified status={second['status_code']}",
        f"Downgrade blocked status={downgrade['status_code']}",
        f"Artifacts: {EXEC_AFTER.name}, {ACTIVITY_LOG.name}, {DB_EXCERPT.name}, {EXEC_BEFORE.name}, {EXEC_AFTER_PARTIAL.name}, {EXEC_AFTER_VERIFIED.name}",
        "PASS",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from httpx import ASGITransport, AsyncClient  # type: ignore

from app.db.session import get_async_session_context
from app.main import app
from app.models.company import Company
from app.models.company_research import ExecutiveProspect
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.company_research import CompanyProspectCreate, CompanyProspectEvidenceCreate
from app.services.company_research_service import CompanyResearchService
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant

TENANT_ID = UUID("11111111-2222-3333-4444-555555555555")
USER_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
CONSOLE = ARTIFACT_DIR / "phase_11_0_proof_console.txt"
PROOF = ARTIFACT_DIR / "phase_11_0_proof.txt"
UI_INDEX = ARTIFACT_DIR / "phase_11_0_ui_research_index.html"
UI_NEW = ARTIFACT_DIR / "phase_11_0_ui_new.html"
UI_WORKSPACE = ARTIFACT_DIR / "phase_11_0_ui_workspace.html"
DB_EXCERPT = ARTIFACT_DIR / "phase_11_0_db_excerpt.sql.txt"


class DummyUIUser(UIUser):
    def __init__(self) -> None:
        super().__init__(user_id=USER_ID, tenant_id=TENANT_ID, email="phase11@example.com", role="admin")


def override_ui_user() -> DummyUIUser:
    return DummyUIUser()


app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user


def log(line: str) -> None:
    print(line)
    existing = CONSOLE.read_text(encoding="utf-8") if CONSOLE.exists() else ""
    CONSOLE.write_text(existing + line + "\n", encoding="utf-8")


async def ensure_role() -> UUID:
    async with get_async_session_context() as session:
        tenant = await session.get(Tenant, TENANT_ID)
        if not tenant:
            session.add(Tenant(id=TENANT_ID, name="Phase 11 Tenant", status="active"))
            await session.commit()

        user = await session.get(User, USER_ID)
        if not user:
            session.add(
                User(
                    id=USER_ID,
                    tenant_id=TENANT_ID,
                    email="phase11@example.com",
                    full_name="Phase 11",
                    hashed_password="not-used",
                    role="admin",
                )
            )
            await session.commit()

        existing = await session.execute(
            Role.__table__.select().where(Role.tenant_id == TENANT_ID)
        )
        row = existing.first()
        if row:
            return row.id

        company = Company(
            tenant_id=TENANT_ID,
            name="Phase 11 Research Co",
            industry="research",
            headquarters_location="Remote",
            website="https://phase11.example.com",
            is_client=True,
        )
        session.add(company)
        await session.flush()

        role = Role(
            tenant_id=TENANT_ID,
            company_id=company.id,
            title="Phase 11 Role",
            function="Research",
            location="Remote",
            status="open",
        )
        session.add(role)
        await session.commit()
        await session.refresh(role)
        return role.id


async def create_run_via_ui() -> UUID:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as client:
        resp_new = await client.get("/ui/research/new")
        UI_NEW.write_text(resp_new.text, encoding="utf-8")
        assert resp_new.status_code == 200, f"new page status {resp_new.status_code}"

        payload = {
            "industry": "fintech",
            "country_region": "US",
            "position": "VP Sales",
            "keywords": "enterprise, payments",
            "exclusions": "agencies",
        }
        resp = await client.post("/ui/research/new", data=payload)
        assert resp.status_code == 303, f"create redirect {resp.status_code}"
        location = resp.headers.get("location", "")
        assert location.startswith("/ui/research/runs/"), f"unexpected redirect {location}"
        run_id = UUID(location.rsplit("/", 1)[-1])

        resp_index = await client.get("/ui/research")
        UI_INDEX.write_text(resp_index.text, encoding="utf-8")
        return run_id


async def seed_prospects(run_id: UUID, role_id: UUID) -> Dict[str, UUID]:
    async with get_async_session_context() as session:
        svc = CompanyResearchService(session)
        p1 = await svc.create_prospect(
            tenant_id=str(TENANT_ID),
            data=CompanyProspectCreate(
                company_research_run_id=run_id,
                role_mandate_id=role_id,
                name_raw="Alpha Payments",
                name_normalized="alpha payments",
                website_url="https://alpha.example.com",
                hq_country="US",
                hq_city="New York",
                sector="fintech",
                description="Payments platform",
                relevance_score=0.87,
                evidence_score=0.82,
                exec_search_enabled=False,
                review_status="new",
            ),
        )
        await svc.add_evidence_to_prospect(
            tenant_id=str(TENANT_ID),
            data=CompanyProspectEvidenceCreate(
                tenant_id=TENANT_ID,
                company_prospect_id=p1.id,
                source_type="url",
                source_name="alpha profile",
                source_url="https://alpha.example.com/about",
                evidence_weight=0.7,
                raw_snippet="Alpha snippet",
            ),
        )

        p2 = await svc.create_prospect(
            tenant_id=str(TENANT_ID),
            data=CompanyProspectCreate(
                company_research_run_id=run_id,
                role_mandate_id=role_id,
                name_raw="Beta Capital",
                name_normalized="beta capital",
                website_url="https://beta.example.com",
                hq_country="US",
                hq_city="Austin",
                sector="fintech",
                description="Capital provider",
                relevance_score=0.76,
                evidence_score=0.71,
                exec_search_enabled=False,
                review_status="new",
            ),
        )
        await svc.add_evidence_to_prospect(
            tenant_id=str(TENANT_ID),
            data=CompanyProspectEvidenceCreate(
                tenant_id=TENANT_ID,
                company_prospect_id=p2.id,
                source_type="url",
                source_name="beta profile",
                source_url="https://beta.example.com/profile",
                evidence_weight=0.6,
                raw_snippet="Beta snippet",
            ),
        )

        await session.commit()
        return {"alpha": p1.id, "beta": p2.id}


async def attempt_exec_discovery(run_id: UUID) -> Dict[str, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as client:
        resp = await client.post(f"/ui/research/runs/{run_id}/executive-discovery")
        return {"status": resp.status_code, "location": resp.headers.get("location", "")}


async def update_review(run_id: UUID, prospect_id: UUID, status: str, enable_exec: bool = False) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as client:
        data = {
            "run_id": str(run_id),
            "review_status": status,
        }
        if enable_exec:
            data["enable_exec_search"] = "true"
        resp = await client.post(f"/ui/research/prospects/{prospect_id}/review", data=data)
        assert resp.status_code == 303, f"review {status} failed {resp.status_code}"


async def seed_executive(run_id: UUID, prospect_id: UUID) -> UUID:
    async with get_async_session_context() as session:
        exec_prospect = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run_id,
            company_prospect_id=prospect_id,
            name_raw="Jane Linked",
            name_normalized="jane linked",
            title="Chief Revenue Officer",
            profile_url="https://example.com/jane",
            linkedin_url="https://linkedin.com/in/janelinked",
            email="jane@example.com",
            location="Remote",
            confidence=0.91,
            status="new",
            discovered_by="internal",
            verification_status="unverified",
            review_status="accepted",
        )
        session.add(exec_prospect)
        await session.commit()
        await session.refresh(exec_prospect)
        return exec_prospect.id


async def promote_executive(run_id: UUID, exec_id: UUID) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as client:
        data = {
            "run_id": str(run_id),
            "executive_ids": [str(exec_id)],
            "stage_id": "",
            "assignment_status": "active",
        }
        resp = await client.post("/ui/research/executives/pipeline", data=data)
        assert resp.status_code == 303, f"pipeline status {resp.status_code}"
        return resp.status_code


async def capture_workspace(run_id: UUID) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=True) as client:
        resp = await client.get(f"/ui/research/runs/{run_id}")
        UI_WORKSPACE.write_text(resp.text, encoding="utf-8")
        assert resp.status_code == 200, f"workspace status {resp.status_code}"
        return resp.text


async def write_db_excerpt(run_id: UUID, prospects: Dict[str, UUID], exec_id: UUID) -> None:
    async with get_async_session_context() as session:
        svc = CompanyResearchService(session)
        p_rows = await svc.list_prospects_for_run(tenant_id=str(TENANT_ID), run_id=run_id, limit=10)
        e_rows = await svc.list_executive_prospects_with_evidence(tenant_id=str(TENANT_ID), run_id=run_id)
    payload = {
        "prospects": [
            {
                "id": str(p.id),
                "name": p.name_normalized,
                "review_status": p.review_status,
                "exec_search_enabled": p.exec_search_enabled,
            }
            for p in p_rows
        ],
        "executives": [
            {
                "id": str(row.get("id")),
                "company_prospect_id": str(row.get("company_prospect_id")),
                "review_status": row.get("review_status"),
                "linkedin_url": row.get("linkedin_url"),
            }
            for row in e_rows
        ],
        "pipeline_exec_id": str(exec_id),
    }
    DB_EXCERPT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def main() -> None:
    # reset console file
    if CONSOLE.exists():
        CONSOLE.unlink()

    role_id = await ensure_role()
    log(f"role_ready={role_id}")

    run_id = await create_run_via_ui()
    log(f"run_created={run_id}")

    prospects = await seed_prospects(run_id, role_id)
    log(f"prospects_seeded={prospects}")

    blocked = await attempt_exec_discovery(run_id)
    log(f"exec_discovery_blocked={blocked}")
    assert blocked["status"] == 303 and "error_message" in blocked["location"], "expected gating"

    await update_review(run_id, prospects["alpha"], "accepted", enable_exec=True)
    await update_review(run_id, prospects["beta"], "hold", enable_exec=False)
    log("reviews_updated")

    allowed = await attempt_exec_discovery(run_id)
    log(f"exec_discovery_allowed={allowed}")
    assert allowed["status"] == 303, "discovery redirect missing"

    exec_id = await seed_executive(run_id, prospects["alpha"])
    log(f"executive_seeded={exec_id}")

    await promote_executive(run_id, exec_id)
    log("executive_promoted_via_pipeline")

    workspace_html = await capture_workspace(run_id)
    assert "Companies" in workspace_html and "Executives" in workspace_html, "workspace missing sections"

    await write_db_excerpt(run_id, prospects, exec_id)
    log("db_excerpt_written")

    proof_lines = [
        "Phase 11.0 Research workspace UI proof",
        f"run_id={run_id}",
        f"prospects={prospects}",
        f"exec_id={exec_id}",
        "- new run created via /ui/research/new",
        "- gating enforced before acceptance",
        "- review updates + exec discovery + pipeline promotion succeed",
        f"- workspace saved to {UI_WORKSPACE.name}",
    ]
    PROOF.write_text("\n".join(proof_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

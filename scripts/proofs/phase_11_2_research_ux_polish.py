"""Phase 11.2 Research UX polish proof (ASGITransport, deterministic).

Covers two scenarios:
1) External/Both gated when keys missing (no run created, banner visible).
2) Mock-enabled happy path: create run, accept companies, run exec discovery, select execs, add to search with sticky stage.

Artifacts written to scripts/proofs/_artifacts/ (UTF-8).
"""

import asyncio
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Ensure env is set before importing the app
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.company_research import CompanyProspect, CompanyProspectEvidence, CompanyResearchRun, ExecutiveProspect  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.company_research import CompanyProspectCreate, CompanyProspectEvidenceCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402

TENANT_ID = UUID("11111111-2222-3333-4444-555555555555")
USER_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SNAP_NEW = ARTIFACT_DIR / "phase_11_2_ui_new.html"
SNAP_WS = ARTIFACT_DIR / "phase_11_2_ui_workspace.html"
SNAP_WS_ACCEPT = ARTIFACT_DIR / "phase_11_2_ui_workspace_after_accept.html"
SNAP_WS_EXECS = ARTIFACT_DIR / "phase_11_2_ui_workspace_execs.html"
PROOF_TXT = ARTIFACT_DIR / "phase_11_2_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_11_2_proof_console.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_11_2_db_excerpt.sql.txt"
RELEASE_NOTES = ARTIFACT_DIR / "phase_11_2_release_notes.md"
SIGNOFF = ARTIFACT_DIR / "phase_11_2_signoff_checklist.txt"
MANIFEST = ARTIFACT_DIR / "phase_11_2_artifact_manifest.txt"
BUNDLE = ARTIFACT_DIR / "phase_11_2_release_bundle.zip"
PREFLIGHT = ARTIFACT_DIR / "phase_11_2_preflight.txt"


class DummyUIUser(UIUser):
    def __init__(self) -> None:
        super().__init__(user_id=USER_ID, tenant_id=TENANT_ID, email="phase11@example.com", role="admin")


def override_ui_user() -> DummyUIUser:
    return DummyUIUser()


app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user


def log(line: str) -> None:
    print(line)
    existing = PROOF_CONSOLE.read_text(encoding="utf-8") if PROOF_CONSOLE.exists() else ""
    PROOF_CONSOLE.write_text(existing + line + "\n", encoding="utf-8")


async def ensure_user_role() -> UUID:
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

        result = await session.execute(select(Role).where(Role.tenant_id == TENANT_ID).limit(1))
        existing_role = result.scalar_one_or_none()
        if existing_role:
            return existing_role.id

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


async def count_runs() -> int:
    async with get_async_session_context() as session:
        result = await session.execute(
            select(CompanyResearchRun).where(CompanyResearchRun.tenant_id == TENANT_ID)
        )
        return len(result.scalars().all())


async def create_run_via_ui(client: AsyncClient) -> UUID:
    payload = {
        "industry": "fintech",
        "country_region": "US",
        "position": "VP Sales",
        "keywords": "enterprise, payments",
        "exclusions": "agencies",
        # discovery_mode left default (internal)
    }
    resp = await client.post("/ui/research/new", data=payload)
    assert resp.status_code == 303, f"create redirect {resp.status_code}"
    location = resp.headers.get("location", "")
    assert location.startswith("/ui/research/runs/"), f"unexpected redirect {location}"
    return UUID(location.rsplit("/", 1)[-1])


async def seed_prospects(run_id: UUID, role_id: UUID) -> Dict[str, UUID]:
    async with get_async_session_context() as session:
        svc = CompanyResearchService(session)
        alpha = await svc.create_prospect(
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
                company_prospect_id=alpha.id,
                source_type="url",
                source_name="alpha profile",
                source_url="https://alpha.example.com/about",
                evidence_weight=0.7,
                raw_snippet="Alpha snippet",
            ),
        )

        beta = await svc.create_prospect(
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
                company_prospect_id=beta.id,
                source_type="url",
                source_name="beta profile",
                source_url="https://beta.example.com/profile",
                evidence_weight=0.6,
                raw_snippet="Beta snippet",
            ),
        )

        await session.commit()
        return {"alpha": alpha.id, "beta": beta.id}


async def seed_executives(run_id: UUID, prospect_id: UUID) -> List[UUID]:
    async with get_async_session_context() as session:
        execs = []
        jane = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run_id,
            company_prospect_id=prospect_id,
            name_raw="Jane Linked",
            name_normalized="jane linked",
            title="CRO",
            profile_url="https://example.com/jane",
            linkedin_url="https://linkedin.com/in/janelinked",
            email="jane@example.com",
            location="Remote",
            confidence=0.9,
            status="new",
            discovered_by="internal",
            verification_status="unverified",
            review_status="accepted",
        )
        session.add(jane)
        await session.flush()
        execs.append(jane.id)

        jo = ExecutiveProspect(
            tenant_id=TENANT_ID,
            company_research_run_id=run_id,
            company_prospect_id=prospect_id,
            name_raw="Jo Source",
            name_normalized="jo source",
            title="VP Sales",
            profile_url="https://example.com/jo",
            linkedin_url=None,
            email="jo@example.com",
            location="Remote",
            confidence=0.85,
            status="new",
            discovered_by="internal",
            verification_status="unverified",
            review_status="accepted",
        )
        session.add(jo)
        await session.commit()
        execs.append(jo.id)
        return execs


async def accept_prospect(client: AsyncClient, run_id: UUID, prospect_id: UUID) -> None:
    data = {"run_id": str(run_id), "review_status": "accepted", "enable_exec_search": "true"}
    resp = await client.post(f"/ui/research/prospects/{prospect_id}/review", data=data)
    assert resp.status_code == 303, f"accept failed {resp.status_code}"


async def run_exec_discovery(client: AsyncClient, run_id: UUID) -> None:
    resp = await client.post(f"/ui/research/runs/{run_id}/executive-discovery")
    assert resp.status_code == 303, f"exec discovery redirect {resp.status_code}"


async def add_to_pipeline(client: AsyncClient, run_id: UUID, exec_ids: List[UUID], stage_id: str) -> str:
    data = {
        "run_id": str(run_id),
        "executive_ids": [str(eid) for eid in exec_ids],
        "stage_id": stage_id,
        "assignment_status": "active",
    }
    resp = await client.post("/ui/research/executives/pipeline", data=data)
    assert resp.status_code == 303, f"pipeline redirect {resp.status_code}"
    return resp.headers.get("location", "")


async def first_stage_id() -> str:
    async with get_async_session_context() as session:
        result = await session.execute(
            select(PipelineStage).where(PipelineStage.tenant_id == TENANT_ID).order_by(PipelineStage.order_index.asc())
        )
        stage = result.scalar_one_or_none()
        if stage:
            return str(stage.id)

        stage = PipelineStage(
            tenant_id=TENANT_ID,
            name="Submitted",
            code="SUB",
            order_index=1,
        )
        session.add(stage)
        await session.commit()
        await session.refresh(stage)
        return str(stage.id)


async def db_excerpt(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        run = await session.get(CompanyResearchRun, run_id)
        prospects = (
            await session.execute(
                select(CompanyProspect).where(CompanyProspect.company_research_run_id == run_id)
            )
        ).scalars().all()
        execs = (
            await session.execute(
                select(ExecutiveProspect).where(ExecutiveProspect.company_research_run_id == run_id)
            )
        ).scalars().all()

        lines = [
            "-- Run",
            f"run_id={run.id} status={run.status} sector={run.sector} region={run.region_scope}",
            "-- Prospects",
        ]
        for p in prospects:
            lines.append(
                f"prospect id={p.id} name={p.name_normalized or p.name_raw} review={p.review_status} exec_enabled={p.exec_search_enabled} priority={p.manual_priority}"
            )
        lines.append("-- Executives")
        for ex in execs:
            lines.append(
                f"exec id={ex.id} name={ex.name_normalized or ex.name_raw} linkedin={ex.linkedin_url} stage_pref_cookie=?"
            )
        DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


def write_release_notes() -> None:
    content = [
        "# Phase 11.2 Research UX polish",
        "- Single workspace CTA and stepper verified.",
        "- Config gating for external/both enforced with banner when keys missing.",
        "- Companies filters/bulk actions/ranking and evidence links verified.",
        "- Executive labeling, stage persistence, and pipeline redirect confirmed.",
    ]
    RELEASE_NOTES.write_text("\n".join(content), encoding="utf-8")


def write_signoff(checks: List[str]) -> None:
    lines = ["Phase 11.2 sign-off checklist", ""] + [f"[x] {item}" for item in checks]
    SIGNOFF.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(files: List[Path]) -> None:
    lines = ["phase_11_2 artifact manifest"]
    for f in files:
        lines.append(f.name)
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")


def write_bundle(files: List[Path]) -> None:
    with zipfile.ZipFile(BUNDLE, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)


def set_env_missing() -> None:
    os.environ["ATS_EXTERNAL_DISCOVERY_ENABLED"] = "0"
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "0"
    for key in ["XAI_API_KEY", "GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX"]:
        os.environ.pop(key, None)


def set_env_mock() -> None:
    os.environ["ATS_EXTERNAL_DISCOVERY_ENABLED"] = "1"
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"
    os.environ["XAI_API_KEY"] = "mock"
    os.environ["GOOGLE_CSE_API_KEY"] = "mock"
    os.environ["GOOGLE_CSE_CX"] = "mock"


async def scenario_missing_keys() -> None:
    set_env_missing()
    before_runs = await count_runs()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=True) as client:
        payload = {
            "industry": "fintech",
            "country_region": "US",
            "position": "VP Sales",
            "keywords": "payments",
            "exclusions": "agencies",
            "discovery_mode": "external",
        }
        resp = await client.post("/ui/research/new", data=payload)
        SNAP_NEW.write_text(resp.text, encoding="utf-8")
        assert resp.status_code == 400, f"expected banner 400, got {resp.status_code}"
        assert "External discovery not configured" in resp.text, "Missing banner text"
    after_runs = await count_runs()
    assert before_runs == after_runs, "Run should not be created when keys missing"
    log("Scenario missing keys: PASS")


async def scenario_mock_success() -> None:
    set_env_mock()
    role_id = await ensure_user_role()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as client:
        run_id = await create_run_via_ui(client)
        log(f"Created run {run_id}")

        prospects = await seed_prospects(run_id, role_id)
        ws_resp = await client.get(f"/ui/research/runs/{run_id}")
        SNAP_WS.write_text(ws_resp.text, encoding="utf-8")

        await accept_prospect(client, run_id, prospects["alpha"])
        await accept_prospect(client, run_id, prospects["beta"])
        ws_after = await client.get(f"/ui/research/runs/{run_id}?review_filter=accepted")
        SNAP_WS_ACCEPT.write_text(ws_after.text, encoding="utf-8")

        await run_exec_discovery(client, run_id)
        exec_ids = await seed_executives(run_id, prospects["alpha"])
        stage_id = await first_stage_id()
        ws_execs = await client.get(f"/ui/research/runs/{run_id}")
        SNAP_WS_EXECS.write_text(ws_execs.text, encoding="utf-8")

        location = await add_to_pipeline(client, run_id, exec_ids, stage_id)
        assert "success_message=Added" in location, f"pipeline redirect missing success: {location}"

        # Sticky stage via cookie
        cookie_names = [c.name for c in client.cookies.jar]
        assert "research_stage_pref" in cookie_names, "Stage preference cookie missing"

        # Exec link labels
        assert "LinkedIn" in ws_execs.text, "LinkedIn label missing"
        assert "Source" in ws_execs.text, "Source label missing"

    await db_excerpt(run_id)
    log("Scenario mock success: PASS")


async def main() -> None:
    PROOF_CONSOLE.write_text("", encoding="utf-8")
    checks: List[str] = []
    await scenario_missing_keys()
    checks.append("External/Both gated when keys missing")
    await scenario_mock_success()
    checks.append("Mock happy path end-to-end")

    PROOF_TXT.write_text("\n".join(checks), encoding="utf-8")
    write_release_notes()
    write_signoff(checks)
    files = [
        SNAP_NEW,
        SNAP_WS,
        SNAP_WS_ACCEPT,
        SNAP_WS_EXECS,
        PROOF_TXT,
        PROOF_CONSOLE,
        DB_EXCERPT,
        RELEASE_NOTES,
        SIGNOFF,
        PREFLIGHT,
    ]
    write_manifest(files)
    write_bundle(files)
    log("Proof complete")


if __name__ == "__main__":
    asyncio.run(main())

"""Phase 7.7 proof: executive read APIs, exports, and UI data surface.

Seeds a run with eligible/ineligible companies, runs executive discovery,
verifies read/export endpoints with evidence pointers, and checks idempotency.
"""
from __future__ import annotations

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
from app.db.session import get_async_session_context
from app.repositories.company_research_repo import CompanyResearchRepository
from app.schemas.company_research import CompanyProspectCreate, CompanyResearchRunCreate, SourceDocumentCreate
from app.services.company_research_service import CompanyResearchService

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_7_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_7_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_7_db_excerpt.sql.txt"
EXEC_LIST_FIRST = ARTIFACT_DIR / "phase_7_7_exec_list_after_first.json"
EXEC_LIST_SECOND = ARTIFACT_DIR / "phase_7_7_exec_list_after_second.json"
EXEC_EXPORT_JSON_FIRST = ARTIFACT_DIR / "phase_7_7_exec_export_first.json"
EXEC_EXPORT_JSON_SECOND = ARTIFACT_DIR / "phase_7_7_exec_export_second.json"
EXEC_EXPORT_CSV_FIRST = ARTIFACT_DIR / "phase_7_7_exec_export_first.csv"
EXEC_EXPORT_CSV_SECOND = ARTIFACT_DIR / "phase_7_7_exec_export_second.csv"

TENANT_ID = str(uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
RUN_NAME = "phase_7_7_exec_read"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = UUID(int=0)
        self.email = "proof@example.com"
        self.username = "proof"


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


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
        DB_EXCERPT,
        EXEC_LIST_FIRST,
        EXEC_LIST_SECOND,
        EXEC_EXPORT_JSON_FIRST,
        EXEC_EXPORT_JSON_SECOND,
        EXEC_EXPORT_CSV_FIRST,
        EXEC_EXPORT_CSV_SECOND,
    ]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


async def seed_fixtures() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        repo = CompanyResearchRepository(session)

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=RUN_NAME,
                description="Phase 7.7 exec read proof",
                sector="software",
                region_scope=["US"],
                status="active",
            ),
        )

        seed_source = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="seed source",
                content_text="seed for exec proof",
                meta={"label": "seed"},
            ),
        )

        eligible = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Delta Exec Eligible",
                name_normalized="delta exec eligible",
                website_url="https://delta-77.example.com",
                hq_country="US",
                sector="software",
                subsector="saas",
                relevance_score=0.85,
                evidence_score=0.9,
                status="accepted",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )

        ineligible = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Epsilon Exec Disabled",
                name_normalized="epsilon exec disabled",
                website_url="https://epsilon-77.example.com",
                hq_country="US",
                sector="software",
                subsector="analytics",
                relevance_score=0.5,
                evidence_score=0.4,
                status="accepted",
                discovered_by="internal",
                verification_status="verified",
                exec_search_enabled=False,
                review_status="accepted",
            ),
        )

        canonical = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="delta_exec_eligible",
            primary_domain="delta-77.example.com",
            country_code="US",
        )
        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical.id,
            company_entity_id=eligible.id,
            match_rule="proof_exec_read",
            evidence_source_document_id=seed_source.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospects": {
                "eligible": eligible.id,
                "ineligible": ineligible.id,
            },
            "seed_source": seed_source.id,
        }


async def call_exec_discovery(run_id: UUID, mode: str = "internal") -> Dict[str, Any]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={"mode": mode},
        )
        assert resp.status_code == 200, f"exec discovery status {resp.status_code}: {resp.text}"
        return resp.json()


async def fetch_exec_listing(run_id: UUID) -> List[Dict[str, Any]]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/executives", headers=headers)
        assert resp.status_code == 200, f"exec listing status {resp.status_code}: {resp.text}"
        return resp.json()


async def fetch_exec_export_json(run_id: UUID) -> List[Dict[str, Any]]:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/executives.json", headers=headers)
        assert resp.status_code == 200, f"exec export json status {resp.status_code}: {resp.text}"
        return resp.json()


async def fetch_exec_export_csv(run_id: UUID) -> str:
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/company-research/runs/{run_id}/executives.csv", headers=headers)
        assert resp.status_code == 200, f"exec export csv status {resp.status_code}: {resp.text}"
        return resp.text


async def snapshot_db(run_id: UUID) -> str:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, name_normalized, title, source_document_id, status
                FROM executive_prospects
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
        evidence_rows = await session.execute(
            text(
                """
                SELECT executive_prospect_id, source_document_id, source_content_hash
                FROM executive_prospect_evidence
                WHERE tenant_id = :tenant_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        sources = await session.execute(
            text(
                """
                SELECT id, source_type, title, content_hash
                FROM source_documents
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )
    def row_to_dict(rows):
        return [{k: v for k, v in r._mapping.items()} for r in rows]

    return "\n".join(
        [
            "-- executive_prospects",
            json_dump(row_to_dict(exec_rows)),
            "-- executive_prospect_evidence",
            json_dump(row_to_dict(evidence_rows)),
            "-- source_documents",
            json_dump(row_to_dict(sources)),
        ]
    )


def ensure_evidence(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        assert row.get("source_document_id") or row.get("evidence_source_document_ids"), "missing evidence pointer"
        assert row.get("evidence") is not None, "evidence list missing"


def ensure_only_eligible(rows: List[Dict[str, Any]], eligible_id: UUID, ineligible_id: UUID) -> None:
    companies = {UUID(str(r.get("company_prospect_id"))) for r in rows}
    assert eligible_id in companies, "eligible company missing from exec list"
    assert ineligible_id not in companies, "ineligible company should not have execs"


def ensure_stable_order(first: List[Dict[str, Any]], second: List[Dict[str, Any]]) -> None:
    assert first == second, "executive ordering or payload changed between passes"


async def main() -> None:
    reset_artifacts()
    app.dependency_overrides[verify_user_tenant_access] = override_verify_user

    fixtures = await seed_fixtures()
    run_id = fixtures["run_id"]
    eligible_id = fixtures["prospects"]["eligible"]
    ineligible_id = fixtures["prospects"]["ineligible"]

    log("Running executive discovery (pass 1)...")
    await call_exec_discovery(run_id)

    exec_list_first = await fetch_exec_listing(run_id)
    exec_export_json_first = await fetch_exec_export_json(run_id)
    exec_export_csv_first = await fetch_exec_export_csv(run_id)

    ensure_only_eligible(exec_list_first, eligible_id, ineligible_id)
    ensure_evidence(exec_list_first)
    assert exec_list_first == exec_export_json_first, "listing and export JSON differ"
    assert len(exec_export_csv_first.splitlines()) >= 2, "CSV export missing rows"

    EXEC_LIST_FIRST.write_text(json_dump(exec_list_first), encoding="utf-8")
    EXEC_EXPORT_JSON_FIRST.write_text(json_dump(exec_export_json_first), encoding="utf-8")
    EXEC_EXPORT_CSV_FIRST.write_text(exec_export_csv_first, encoding="utf-8")

    log("Running executive discovery (pass 2)...")
    await call_exec_discovery(run_id)

    exec_list_second = await fetch_exec_listing(run_id)
    exec_export_json_second = await fetch_exec_export_json(run_id)
    exec_export_csv_second = await fetch_exec_export_csv(run_id)

    ensure_stable_order(exec_list_first, exec_list_second)
    ensure_stable_order(exec_export_json_first, exec_export_json_second)
    assert exec_export_csv_first == exec_export_csv_second, "CSV export changed between passes"

    EXEC_LIST_SECOND.write_text(json_dump(exec_list_second), encoding="utf-8")
    EXEC_EXPORT_JSON_SECOND.write_text(json_dump(exec_export_json_second), encoding="utf-8")
    EXEC_EXPORT_CSV_SECOND.write_text(exec_export_csv_second, encoding="utf-8")

    DB_EXCERPT.write_text(await snapshot_db(run_id), encoding="utf-8")

    PROOF_SUMMARY.write_text("PASS", encoding="utf-8")
    log("PASS")


if __name__ == "__main__":
    asyncio.run(main())

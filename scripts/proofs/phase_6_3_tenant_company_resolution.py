import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.db.session import get_async_session_context
from app.schemas.company_research import (
    CompanyProspectCreate,
    CompanyProspectEvidenceCreate,
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from app.services.company_research_service import CompanyResearchService
from app.workers.company_research_worker import run_worker

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_6_3_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_6_3_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_6_3_db_excerpt.sql.txt"
CANONICAL_JSON = ARTIFACT_DIR / "phase_6_3_canonical_companies.json"
LINKS_JSON = ARTIFACT_DIR / "phase_6_3_links.json"
SOURCES_JSON = ARTIFACT_DIR / "phase_6_3_sources_used.json"

TENANT_ID = str(uuid.uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
SHARED_DOMAIN = "phase63-proof.example.com"


def log(line: str) -> None:
    print(line)


def serialize_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
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


async def create_run_with_company(label: str) -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=f"phase6_3_run_{label}_{uuid.uuid4().hex[:6]}",
                description=f"Phase 6.3 proof {label}",
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
                content_text=f"Proof source {label} for {SHARED_DOMAIN}",
                meta={"kind": "text", "label": f"proof_{label}"},
            ),
        )

        prospect = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw=f"ProofCo {label}",
                name_normalized=f"proofco {label}",
                website_url=f"https://{SHARED_DOMAIN}",
                hq_country="US",
                sector="demo",
                subsector="proof",
                employees_band="50-100",
                revenue_band_usd="1-5m",
                description=f"Proof company {label}",
                data_confidence=0.9,
                relevance_score=0.9,
                evidence_score=0.9,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=True,
            ),
        )

        await service.add_evidence_to_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectEvidenceCreate(
                tenant_id=UUID(TENANT_ID),
                company_prospect_id=prospect.id,
                source_type="text",
                source_name=f"proof_evidence_{label}",
                source_url=source.url or f"https://{SHARED_DOMAIN}/source/{label.lower()}",
                raw_snippet=f"Evidence {label} for {SHARED_DOMAIN}",
                evidence_weight=0.8,
                source_document_id=source.id,
                source_content_hash=source.content_hash,
            ),
        )

        job = await service.start_run(tenant_id=TENANT_ID, run_id=run.id)

        return {
            "run_id": run.id,
            "job_id": job.id,
            "source_id": source.id,
            "prospect_id": prospect.id,
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


async def fetch_canonical_state() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        data: Dict[str, Any] = {}

        canonical_rows = await session.execute(
            text(
                """
                SELECT cc.id, cc.tenant_id, cc.canonical_name, cc.primary_domain, cc.country_code,
                       cc.created_at, cc.updated_at
                FROM canonical_companies cc
                WHERE cc.tenant_id = :tenant_id
                ORDER BY cc.created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        data["canonical_companies"] = canonical_rows.fetchall()

        domain_rows = await session.execute(
            text(
                """
                SELECT id, canonical_company_id, domain_normalized, created_at
                FROM canonical_company_domains
                WHERE tenant_id = :tenant_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        data["domains"] = domain_rows.fetchall()

        link_rows = await session.execute(
            text(
                """
                SELECT id, canonical_company_id, company_entity_id, match_rule,
                       evidence_source_document_id, evidence_company_research_run_id
                FROM canonical_company_links
                WHERE tenant_id = :tenant_id
                ORDER BY created_at
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        data["links"] = link_rows.fetchall()

        source_rows = await session.execute(
            text(
                """
                SELECT id, company_research_run_id, source_type, title
                FROM source_documents
                WHERE tenant_id = :tenant_id
                ORDER BY created_at DESC
                LIMIT 20
                """
            ),
            {"tenant_id": TENANT_ID},
        )
        data["sources"] = source_rows.fetchall()

        counts = await session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM canonical_companies WHERE tenant_id = :tenant_id AND primary_domain = :domain) AS canonical_count,
                    (SELECT count(*) FROM canonical_company_domains WHERE tenant_id = :tenant_id AND domain_normalized = :domain) AS domain_count,
                    (SELECT count(*) FROM canonical_company_links WHERE tenant_id = :tenant_id) AS link_count
                """
            ),
            {"tenant_id": TENANT_ID, "domain": SHARED_DOMAIN},
        )
        data["counts"] = counts.fetchone()

        return data


async def run_workers(rounds: int = 8) -> None:
    """Pump the worker a few times to advance all pending steps."""
    for _ in range(rounds):
        await run_worker(loop=False, sleep_seconds=1)


async def main_async() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for artifact in [PROOF_SUMMARY, DB_EXCERPT, CANONICAL_JSON, LINKS_JSON, SOURCES_JSON]:
        artifact.unlink(missing_ok=True)

    log("=== Phase 6.3 tenant-wide canonical company proof ===")
    log(f"Tenant: {TENANT_ID}")
    log(f"Shared domain: {SHARED_DOMAIN}")

    run_a = await create_run_with_company("A")
    run_b = await create_run_with_company("B")
    log(f"Run A {run_a['run_id']}, Run B {run_b['run_id']}")

    await run_workers(rounds=8)

    first_state = await fetch_canonical_state()
    canonical_count_first = first_state["counts"].canonical_count if first_state.get("counts") else 0
    domain_count_first = first_state["counts"].domain_count if first_state.get("counts") else 0
    link_count_first = first_state["counts"].link_count if first_state.get("counts") else 0

    assert canonical_count_first == 1, "Expected exactly one canonical company for shared domain"
    assert domain_count_first >= 1, "Expected canonical domain recorded"
    assert link_count_first >= 2, "Expected at least two links after first pass"

    allowed_sources = {str(run_a["source_id"]), str(run_b["source_id"])}
    for row in first_state["links"]:
        assert row.evidence_source_document_id, "Link missing evidence_source_document_id"
        assert str(row.evidence_source_document_id) in allowed_sources, "Link evidence source not in expected set"

    await reset_steps_for_rerun(UUID(str(run_a["run_id"])))
    await reset_steps_for_rerun(UUID(str(run_b["run_id"])))
    await run_workers(rounds=8)

    second_state = await fetch_canonical_state()
    canonical_count_second = second_state["counts"].canonical_count if second_state.get("counts") else 0
    domain_count_second = second_state["counts"].domain_count if second_state.get("counts") else 0
    link_count_second = second_state["counts"].link_count if second_state.get("counts") else 0

    assert canonical_count_second == canonical_count_first, "Canonical company count changed on rerun"
    assert domain_count_second == domain_count_first, "Canonical domain count changed on rerun"
    assert link_count_second == link_count_first, "Canonical company links count changed on rerun"

    summary_lines = [
        "PASS: Phase 6.3 tenant-wide canonical company resolution",
        f"Tenant: {TENANT_ID}",
        f"Run A: {run_a['run_id']}",
        f"Run B: {run_b['run_id']}",
        f"Shared domain: {SHARED_DOMAIN}",
        f"Canonical companies: {canonical_count_first} (rerun delta {canonical_count_second - canonical_count_first})",
        f"Canonical domains: {domain_count_first} (rerun delta {domain_count_second - domain_count_first})",
        f"Canonical company links: {link_count_first} (rerun delta {link_count_second - link_count_first})",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    CANONICAL_JSON.write_text(json.dumps(serialize_rows(first_state["canonical_companies"]), indent=2) + "\n", encoding="utf-8")
    LINKS_JSON.write_text(json.dumps(serialize_rows(first_state["links"]), indent=2) + "\n", encoding="utf-8")
    SOURCES_JSON.write_text(json.dumps(serialize_rows(first_state["sources"]), indent=2) + "\n", encoding="utf-8")

    db_lines = [
        "SELECT id, canonical_name, primary_domain, country_code FROM canonical_companies WHERE tenant_id = '{tenant}' AND primary_domain = '{domain}';".format(tenant=TENANT_ID, domain=SHARED_DOMAIN),
        json.dumps(serialize_rows(first_state["canonical_companies"]), indent=2),
        "",
        "SELECT id, canonical_company_id, domain_normalized FROM canonical_company_domains WHERE tenant_id = '{tenant}';".format(tenant=TENANT_ID),
        json.dumps(serialize_rows(first_state["domains"]), indent=2),
        "",
        "SELECT id, canonical_company_id, company_entity_id, match_rule, evidence_source_document_id, evidence_company_research_run_id FROM canonical_company_links WHERE tenant_id = '{tenant}';".format(tenant=TENANT_ID),
        json.dumps(serialize_rows(first_state["links"]), indent=2),
    ]
    DB_EXCERPT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")

    log("PASS: Phase 6.3 proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())

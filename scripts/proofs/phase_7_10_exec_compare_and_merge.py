"""Phase 7.10 proof: executive compare + merge decisions.

Deterministically seeds a run, runs dual-engine executive discovery, exercises
the compare API, posts mark_same and keep_separate merge decisions with
evidence pointers, verifies ActivityLog entries, and reruns the flow to assert
idempotency (no duplicate executives, decisions, or evidence). Writes required
artifacts and ends with PASS.
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
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_10_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_10_proof.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_10_db_excerpt.sql.txt"
COMPARE_BEFORE = ARTIFACT_DIR / "phase_7_10_compare_before.json"
COMPARE_AFTER_MARK_SAME = ARTIFACT_DIR / "phase_7_10_compare_after_mark_same.json"
COMPARE_AFTER_KEEP_SEPARATE = ARTIFACT_DIR / "phase_7_10_compare_after_keep_separate.json"

TENANT_ID = str(uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
RUN_NAME = "phase_7_10_exec_compare"


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
        COMPARE_BEFORE,
        COMPARE_AFTER_MARK_SAME,
        COMPARE_AFTER_KEEP_SEPARATE,
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
                description="Phase 7.10 executive compare proof",
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
                title="exec-proof-seed",
                content_text="seed for exec compare",
                meta={"label": "seed"},
            ),
        )

        company = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="Delta Exec Proof",
                name_normalized="delta exec proof",
                website_url="https://delta-710.example.com",
                hq_country="US",
                sector="software",
                subsector="infra",
                relevance_score=0.92,
                evidence_score=0.9,
                status="accepted",
                discovered_by="internal",
                verification_status="partial",
                exec_search_enabled=True,
                review_status="accepted",
            ),
        )

        canonical = await repo.create_canonical_company(
            tenant_id=TENANT_ID,
            canonical_name="delta_exec_proof",
            primary_domain="delta-710.example.com",
            country_code="US",
        )
        await repo.upsert_canonical_company_link(
            tenant_id=TENANT_ID,
            canonical_company_id=canonical.id,
            company_entity_id=company.id,
            match_rule="proof_exec_compare",
            evidence_source_document_id=seed_source.id,
            evidence_company_research_run_id=run.id,
        )

        await session.commit()

        return {
            "run_id": run.id,
            "company_id": company.id,
            "canonical_company_id": canonical.id,
            "seed_source": seed_source.id,
        }


def build_external_payload(company_name: str) -> dict:
    slug = company_name.lower().replace(" ", "-")
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "generated_at": "2026-01-01T00:00:00Z",
        "query": "phase_7_10_external_proof",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_name.lower(),
                "executives": [
                    {
                        "name": "Alex Delta Chief Executive",
                        "title": "Chief Executive Officer",
                        "profile_url": f"https://external.example.com/{slug}/ceo",
                        "confidence": 0.82,
                        "evidence": [
                            {
                                "url": f"https://external.example.com/{slug}/ceo",
                                "label": "Ext CEO page",
                                "kind": "external",
                                "snippet": "CEO listing from external engine",
                            }
                        ],
                    },
                    {
                        "name": "Blair Delta Finance Lead",
                        "title": "Chief Financial Officer",
                        "profile_url": f"https://external.example.com/{slug}/cfo",
                        "confidence": 0.78,
                        "evidence": [
                            {
                                "url": f"https://external.example.com/{slug}/cfo",
                                "label": "Ext CFO page",
                                "kind": "external",
                                "snippet": "CFO listing from external engine",
                            }
                        ],
                    },
                ],
            }
        ],
    }


async def run_discovery(client: AsyncClient, run_id: UUID, company_name: str) -> dict:
    resp = await client.post(
        f"/company-research/runs/{run_id}/executive-discovery/run",
        headers={"X-Tenant-ID": TENANT_ID},
        json={
            "mode": "both",
            "engine": "external",
            "provider": "external_engine",
            "model": "mock-model",
            "title": "Dual engine exec discovery",
            "payload": build_external_payload(company_name),
        },
    )
    assert resp.status_code == 200, f"exec discovery status {resp.status_code}: {resp.text}"
    return resp.json()


async def fetch_compare(client: AsyncClient, run_id: UUID) -> dict:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-compare",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200, f"compare status {resp.status_code}: {resp.text}"
    return resp.json()


def collect_leaves(compare_body: dict) -> List[dict]:
    leaves: List[dict] = []
    for item in compare_body.get("matched_or_both", []):
        if item.get("internal"):
            leaves.append(item["internal"])
        if item.get("external"):
            leaves.append(item["external"])
    leaves.extend(compare_body.get("internal_only", []))
    leaves.extend(compare_body.get("external_only", []))
    for cand in compare_body.get("candidate_matches", []):
        if cand.get("internal"):
            leaves.append(cand["internal"])
        if cand.get("external"):
            leaves.append(cand["external"])
    return leaves


def assert_evidence_blocks(compare_body: dict) -> None:
    leaves = collect_leaves(compare_body)
    assert leaves, "no leaves returned"
    for leaf in leaves:
        evidence = leaf.get("evidence") or {}
        has_pointer = (
            evidence.get("request_source_document_id")
            or evidence.get("response_source_document_id")
            or (evidence.get("evidence_source_document_ids") or [])
            or evidence.get("enrichment_record_id")
        )
        assert has_pointer, f"missing evidence pointers for {leaf}"


def assert_candidates_or_matches(compare_body: dict) -> None:
    if compare_body.get("candidate_matches"):
        return
    if compare_body.get("matched_or_both"):
        return
    raise AssertionError("compare response missing candidates and matched rows")


async def post_decision(
    client: AsyncClient,
    *,
    run_id: UUID,
    decision_type: str,
    left_id: UUID,
    right_id: UUID,
    note: str,
    evidence_doc_ids: List[UUID],
    evidence_enrichment_ids: List[UUID],
) -> dict:
    resp = await client.post(
        f"/company-research/runs/{run_id}/executives-merge-decision",
        headers={"X-Tenant-ID": TENANT_ID},
        json={
            "decision_type": decision_type,
            "left_executive_id": str(left_id),
            "right_executive_id": str(right_id),
            "note": note,
            "evidence_source_document_ids": [str(e) for e in evidence_doc_ids],
            "evidence_enrichment_ids": [str(e) for e in evidence_enrichment_ids],
        },
    )
    assert resp.status_code == 200, f"decision {decision_type} failed: {resp.status_code} {resp.text}"
    return resp.json()


def gather_evidence_ids(match: dict) -> tuple[List[UUID], List[UUID]]:
    docs: set[str] = set()
    enrich: set[str] = set()
    for side in [match.get("internal"), match.get("external")]:
        if not side:
            continue
        evidence = side.get("evidence") or {}
        if evidence.get("request_source_document_id"):
            docs.add(str(evidence["request_source_document_id"]))
        if evidence.get("response_source_document_id"):
            docs.add(str(evidence["response_source_document_id"]))
        for eid in evidence.get("evidence_source_document_ids") or []:
            docs.add(str(eid))
        if evidence.get("enrichment_record_id"):
            enrich.add(str(evidence["enrichment_record_id"]))
    return [UUID(d) for d in docs], [UUID(e) for e in enrich]


async def fetch_activity_and_decisions(run_id: UUID) -> Dict[str, Any]:
    async with get_async_session_context() as session:
        activity_rows = await session.execute(
            text(
                """
                SELECT type, message, created_by, created_at
                FROM activity_log
                WHERE tenant_id = :tenant_id AND type = 'EXEC_COMPARE_DECISION'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )

        decision_rows = await session.execute(
            text(
                """
                SELECT id, decision_type, left_executive_id, right_executive_id, evidence_source_document_ids, evidence_enrichment_ids, created_at
                FROM executive_merge_decisions
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )

        return {
            "activity": [dict(r._mapping) for r in activity_rows.fetchall()],
            "decisions": [dict(r._mapping) for r in decision_rows.fetchall()],
        }


async def write_db_excerpt(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, name_normalized, title, discovered_by, verification_status, source_document_id
                FROM executive_prospects
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )

        evidence_rows = await session.execute(
            text(
                """
                SELECT executive_prospect_id, source_document_id, source_url, raw_snippet
                FROM executive_prospect_evidence
                WHERE tenant_id = :tenant_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )

        decision_rows = await session.execute(
            text(
                """
                SELECT id, decision_type, left_executive_id, right_executive_id, evidence_source_document_ids, evidence_enrichment_ids
                FROM executive_merge_decisions
                WHERE tenant_id = :tenant_id AND company_research_run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "run_id": run_id},
        )

        activity_rows = await session.execute(
            text(
                """
                SELECT type, message, created_by, created_at
                FROM activity_log
                WHERE tenant_id = :tenant_id AND type = 'EXEC_COMPARE_DECISION'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID},
        )

    lines = [
        "-- executive_prospects",
        json_dump([dict(r._mapping) for r in exec_rows.fetchall()]),
        "-- executive_prospect_evidence",
        json_dump([dict(r._mapping) for r in evidence_rows.fetchall()]),
        "-- executive_merge_decisions",
        json_dump([dict(r._mapping) for r in decision_rows.fetchall()]),
        "-- activity_log",
        json_dump([dict(r._mapping) for r in activity_rows.fetchall()]),
    ]
    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    app.dependency_overrides[verify_user_tenant_access] = override_verify_user

    fixtures = await seed_fixtures()
    run_id = fixtures["run_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        log("Running exec discovery (pass 1, mode=both)...")
        await run_discovery(client, run_id, "Delta Exec Proof")

        compare_before = await fetch_compare(client, run_id)
        assert_evidence_blocks(compare_before)
        assert_candidates_or_matches(compare_before)
        COMPARE_BEFORE.write_text(json_dump(compare_before), encoding="utf-8")

        candidates = compare_before.get("candidate_matches", [])
        assert candidates, "expected at least one candidate for decisions"

        first = candidates[0]
        docs_a, enrich_a = gather_evidence_ids(first)
        await post_decision(
            client,
            run_id=run_id,
            decision_type="mark_same",
            left_id=UUID(str(first["internal"]["id"])),
            right_id=UUID(str(first["external"]["id"])),
            note="mark_same proof",
            evidence_doc_ids=docs_a,
            evidence_enrichment_ids=enrich_a,
        )

        compare_after_mark = await fetch_compare(client, run_id)
        assert_evidence_blocks(compare_after_mark)
        COMPARE_AFTER_MARK_SAME.write_text(json_dump(compare_after_mark), encoding="utf-8")

        keep_target = candidates[1] if len(candidates) > 1 else candidates[0]
        docs_b, enrich_b = gather_evidence_ids(keep_target)
        await post_decision(
            client,
            run_id=run_id,
            decision_type="keep_separate",
            left_id=UUID(str(keep_target["internal"]["id"])),
            right_id=UUID(str(keep_target["external"]["id"])),
            note="keep_separate proof",
            evidence_doc_ids=docs_b,
            evidence_enrichment_ids=enrich_b,
        )

        compare_after_keep = await fetch_compare(client, run_id)
        assert_evidence_blocks(compare_after_keep)
        COMPARE_AFTER_KEEP_SEPARATE.write_text(json_dump(compare_after_keep), encoding="utf-8")

        first_activity = await fetch_activity_and_decisions(run_id)
        assert len(first_activity["decisions"]) >= 2, "missing merge decisions"
        assert any("mark_same" in (row.get("decision_type") or "") for row in first_activity["decisions"])
        assert any("keep_separate" in (row.get("decision_type") or "") for row in first_activity["decisions"])
        assert any("decision=mark_same" in (row.get("message") or "") for row in first_activity["activity"]), "missing audit log for mark_same"

        log("Running exec discovery (pass 2, idempotency)...")
        await run_discovery(client, run_id, "Delta Exec Proof")
        compare_second = await fetch_compare(client, run_id)
        assert_evidence_blocks(compare_second)

        second_activity = await fetch_activity_and_decisions(run_id)
        assert len(second_activity["decisions"]) == len(first_activity["decisions"]), "decision count changed on re-run"
        assert json_dump(compare_after_keep) == json_dump(compare_second), "compare output changed after rerun"

    await write_db_excerpt(run_id)

    summary_lines = [
        "Phase 7.10 executive compare + merge proof",
        f"Tenant: {TENANT_ID}",
        f"Run: {run_id}",
        f"Artifacts: {COMPARE_BEFORE.name}, {COMPARE_AFTER_MARK_SAME.name}, {COMPARE_AFTER_KEEP_SEPARATE.name}, {DB_EXCERPT.name}, {PROOF_CONSOLE.name}",
        "PASS",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
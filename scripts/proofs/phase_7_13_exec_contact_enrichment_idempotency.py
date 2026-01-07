"""Phase 7.13 proof: explicit executive contact enrichment action with TTL/hash idempotency.

Demonstrates:
- First explicit enrich_contacts call hits provider stub and writes SourceDocument + AIEnrichmentRecord.
- Second call within TTL/hash window is skipped and returns the same source_document_id (no credit waste).
- Evidence is retained and linked to the executive.
Artifacts are written to scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_13_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_13_proof.txt"
FIRST_CALL = ARTIFACT_DIR / "phase_7_13_first_call.json"
SECOND_CALL = ARTIFACT_DIR / "phase_7_13_second_call.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_13_db_excerpt.sql.txt"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_7_13_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_7_13_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID
ROLE_MANDATE_ID = phase_7_10.ROLE_MANDATE_ID


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.email = "proof@example.com"
        self.username = "proof"


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


app.dependency_overrides[verify_user_tenant_access] = override_verify_user


def log(line: str) -> None:
    msg = str(line)
    print(msg)


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


async def fetch_executives(client: AsyncClient, run_id: UUID, company_id: UUID) -> List[dict]:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives",
        headers={"X-Tenant-ID": TENANT_ID},
        params={"company_prospect_id": str(company_id)},
    )
    assert resp.status_code == 200, f"exec list status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list) and data, "no executives returned"
    return data


def _result_source_document_id(payload: dict) -> str:
    results = payload.get("results") or []
    assert results, "results missing"
    doc_id = results[0].get("source_document_id")
    assert doc_id, "source_document_id missing"
    return str(doc_id)


async def write_db_excerpt(executive_id: UUID) -> None:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                """
                SELECT id, company_prospect_id, company_research_run_id, name_normalized, title, linkedin_url,
                       review_status, verification_status, source_document_id, created_at
                FROM executive_prospects
                WHERE tenant_id = :tenant_id AND id = :exec_id
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

        enrichment_rows = await session.execute(
            text(
                """
                SELECT id, provider, purpose, content_hash, source_document_id, status, created_at
                FROM ai_enrichment_record
                WHERE tenant_id = :tenant_id AND target_id = :exec_id AND target_type = 'EXECUTIVE'
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

        research_event_rows = await session.execute(
            text(
                """
                SELECT id, source_type, source_url, entity_type, entity_id, raw_payload
                FROM research_event
                WHERE tenant_id = :tenant_id AND entity_id = :exec_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

        source_document_rows = await session.execute(
            text(
                """
                SELECT id, research_event_id, document_type, title, url, metadata
                FROM source_document
                WHERE tenant_id = :tenant_id AND research_event_id IN (
                    SELECT id FROM research_event WHERE tenant_id = :tenant_id AND entity_id = :exec_id
                )
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

        evidence_rows = await session.execute(
            text(
                """
                SELECT id, source_document_id, source_content_hash, source_name, source_type
                FROM executive_prospect_evidence
                WHERE tenant_id = :tenant_id AND executive_prospect_id = :exec_id
                ORDER BY created_at ASC
                """
            ),
            {"tenant_id": TENANT_ID, "exec_id": str(executive_id)},
        )

    def rows_to_list(rows) -> List[Dict[str, Any]]:
        return [dict(r._mapping) for r in rows.fetchall()] if rows else []

    lines = [
        "-- executive_prospect",
        json.dumps(rows_to_list(exec_rows), indent=2, sort_keys=True, default=str),
        "-- ai_enrichment_record",
        json.dumps(rows_to_list(enrichment_rows), indent=2, sort_keys=True, default=str),
        "-- research_event",
        json.dumps(rows_to_list(research_event_rows), indent=2, sort_keys=True, default=str),
        "-- source_document",
        json.dumps(rows_to_list(source_document_rows), indent=2, sort_keys=True, default=str),
        "-- executive_prospect_evidence",
        json.dumps(rows_to_list(evidence_rows), indent=2, sort_keys=True, default=str),
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
        if "enrich_contacts" in path or ("/executives/" in path and "review-status" in path)
    }
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 7.13 executive contact enrichment proof ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]
    company_id = fixtures["company_id"]
    log(f"Run: {run_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await phase_7_10.run_discovery(client, run_id, "Delta Exec Proof")
        exec_rows = await fetch_executives(client, run_id, company_id)
        exec_rows_sorted = sorted(exec_rows, key=lambda r: r.get("id"))
        executive_id = UUID(exec_rows_sorted[0]["id"])
        log(f"Executive chosen: {executive_id}")

        payload = {"providers": ["lusha"], "force": False, "ttl_minutes": 1440, "mode": "mock"}

        first_resp = await client.post(
            f"/company-research/executives/{executive_id}/enrich_contacts",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )
        assert first_resp.status_code == 200, f"first enrich status {first_resp.status_code}: {first_resp.text}"
        first_payload = first_resp.json()
        dump_json(FIRST_CALL, first_payload)

        second_resp = await client.post(
            f"/company-research/executives/{executive_id}/enrich_contacts",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )
        assert second_resp.status_code == 200, f"second enrich status {second_resp.status_code}: {second_resp.text}"
        second_payload = second_resp.json()
        dump_json(SECOND_CALL, second_payload)

        first_doc = _result_source_document_id(first_payload)
        second_doc = _result_source_document_id(second_payload)
        assert first_doc == second_doc, "source_document_id mismatch across repeated calls"

        first_status = (first_payload.get("results") or [{}])[0].get("status")
        second_status = (second_payload.get("results") or [{}])[0].get("status")
        assert first_status == "created", f"expected first status created, got {first_status}"
        assert second_status == "skipped", f"expected second status skipped, got {second_status}"

        await write_db_excerpt(executive_id)
        await capture_openapi(client)

    summary_lines = [
        "PASS: Phase 7.13 explicit executive contact enrichment idempotency",
        f"Tenant: {TENANT_ID}",
        f"Executive: {executive_id}",
        "First call created provider evidence; second skipped via TTL/hash and reused same source_document_id",
        "Artifacts: first/second call JSON, DB excerpt, openapi after/excerpt, proof summary",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    log("PASS: Phase 7.13 proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())

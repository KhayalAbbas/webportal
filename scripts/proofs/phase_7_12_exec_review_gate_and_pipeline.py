"""Phase 7.12 proof: executive review gate + accepted-only pipeline promotion.

Covers hold->rejected->accepted review flow, ensures pipeline creation is blocked
until accepted, validates idempotent pipeline promotion, and captures audit/DB
artifacts plus OpenAPI excerpts. Artifacts are written to scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
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
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_12_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_12_proof.txt"
EXEC_REVIEW_FIRST = ARTIFACT_DIR / "phase_7_12_exec_review_first.json"
EXEC_REVIEW_SECOND = ARTIFACT_DIR / "phase_7_12_exec_review_second.json"
CREATED_PIPELINE = ARTIFACT_DIR / "phase_7_12_created_pipeline_objects.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_7_12_db_excerpt.sql.txt"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_7_12_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_7_12_openapi_after_excerpt.txt"

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
    # Console is tee'd by the runner; avoid double-writing to the same file on Windows.


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        EXEC_REVIEW_FIRST,
        EXEC_REVIEW_SECOND,
        CREATED_PIPELINE,
        DB_EXCERPT,
        OPENAPI_AFTER,
        OPENAPI_AFTER_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


async def patch_review_status(client: AsyncClient, executive_id: UUID, status: str) -> dict:
    resp = await client.patch(
        f"/company-research/executives/{executive_id}/review-status",
        headers={"X-Tenant-ID": TENANT_ID},
        json={"review_status": status},
    )
    assert resp.status_code == 200, f"review patch {status} failed: {resp.status_code} {resp.text}"
    return resp.json()


async def post_pipeline(client: AsyncClient, executive_id: UUID, expect_status: int) -> dict:
    resp = await client.post(
        f"/company-research/executives/{executive_id}/pipeline",
        headers={"X-Tenant-ID": TENANT_ID},
        json={"assignment_status": "sourced"},
    )
    assert resp.status_code == expect_status, f"pipeline expected {expect_status}, got {resp.status_code}: {resp.text}"
    return resp.json() if resp.text else {"detail": resp.text, "status_code": resp.status_code}


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
                SELECT id, company_prospect_id, review_status, verification_status, created_at, updated_at
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
                WHERE tenant_id = :tenant_id AND type IN ('EXECUTIVE_REVIEW_STATUS','EXECUTIVE_PIPELINE_CREATE')
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
                SELECT id, candidate_id, role_id, status, current_stage_id, source, created_at
                FROM candidate_assignment
                WHERE tenant_id = :tenant_id AND id = :assignment_id
                """
            ),
            {"tenant_id": TENANT_ID, "assignment_id": str(assignment_id)},
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
        if "review-status" in path or "/executives/" in path and "pipeline" in path
    }
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 7.12 executive review gate + pipeline proof ===")
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

        # hold -> pipeline blocked
        hold_patch = await patch_review_status(client, executive_id, "hold")
        blocked_hold = await post_pipeline(client, executive_id, expect_status=409)

        # rejected -> pipeline blocked
        rejected_patch = await patch_review_status(client, executive_id, "rejected")
        blocked_rejected = await post_pipeline(client, executive_id, expect_status=409)

        dump_json(EXEC_REVIEW_FIRST, {
            "hold_patch": hold_patch,
            "blocked_hold": blocked_hold,
            "rejected_patch": rejected_patch,
            "blocked_rejected": blocked_rejected,
        })

        # accepted -> pipeline succeeds
        accepted_patch = await patch_review_status(client, executive_id, "accepted")
        pipeline_first = await post_pipeline(client, executive_id, expect_status=200)
        pipeline_second = await post_pipeline(client, executive_id, expect_status=200)

        dump_json(EXEC_REVIEW_SECOND, {
            "accepted_patch": accepted_patch,
            "pipeline_first": pipeline_first,
            "pipeline_second": pipeline_second,
        })

        assert pipeline_first["candidate_id"] == pipeline_second.get("candidate_id"), "candidate idempotency failed"
        assert pipeline_first.get("assignment_id") == pipeline_second.get("assignment_id"), "assignment idempotency failed"
        assert pipeline_first.get("research_event_id") == pipeline_second.get("research_event_id"), "research_event idempotency failed"

        dump_json(CREATED_PIPELINE, pipeline_first)
        await write_db_excerpt(executive_id, pipeline_first)
        await capture_openapi(client)

    summary_lines = [
        "PASS: Phase 7.12 exec review gate + accepted-only pipeline", 
        f"Tenant: {TENANT_ID}",
        f"Executive: {executive_id}",
        "Flow: hold -> rejected blocked, accepted allowed", 
        "Idempotency: pipeline promotion re-run returned same ids", 
        "Artifacts: proof, db excerpt, openapi after/excerpt, pipeline objects",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    log("PASS: Phase 7.12 proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())

"""Phase 9.7 verification runner: compare UI -> API -> DB evidence path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import app
from app.core.dependencies import verify_user_tenant_access
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant
from app.db.session import AsyncSessionLocal, get_async_session_context


ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
CONSOLE = ARTIFACT_DIR / "phase_9_7_verify_console.txt"
COMPARE_BEFORE = ARTIFACT_DIR / "phase_9_7_verify_compare.json"
COMPARE_AFTER = ARTIFACT_DIR / "phase_9_7_verify_compare_after.json"
MARK_SAME_REQ = ARTIFACT_DIR / "phase_9_7_verify_mark_same_request.json"
MARK_SAME_RESP = ARTIFACT_DIR / "phase_9_7_verify_mark_same_response.json"
KEEP_SEPARATE_REQ = ARTIFACT_DIR / "phase_9_7_verify_keep_separate_request.json"
KEEP_SEPARATE_RESP = ARTIFACT_DIR / "phase_9_7_verify_keep_separate_response.json"
UI_EXCERPT = ARTIFACT_DIR / "phase_9_7_verify_ui_html_excerpt.html"
DB_EXCERPT = ARTIFACT_DIR / "phase_9_7_verify_db_excerpt.txt"


def reset_artifacts(paths: Iterable[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    CONSOLE.parent.mkdir(parents=True, exist_ok=True)
    with CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


async def get_role_tenant_user() -> tuple[UUID, UUID, UUID, str]:
    async with AsyncSessionLocal() as session:
        role_row = (
            await session.execute(
                text("SELECT id, tenant_id FROM role ORDER BY created_at ASC LIMIT 1")
            )
        ).first()
        if not role_row:
            raise RuntimeError("No role found for tenant")

        user_row = (
            await session.execute(
                text('SELECT id, email FROM "user" WHERE tenant_id = :tenant LIMIT 1'),
                {"tenant": role_row.tenant_id},
            )
        ).first()
        if not user_row:
            raise RuntimeError("No user found for tenant")

        return role_row.id, role_row.tenant_id, user_row.id, user_row.email or "verify@example.com"


def make_stub_users(tenant_id: UUID, user_id: UUID, email: str) -> tuple[Any, UIUser]:
    stub = type(
        "StubUser",
        (),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "role": "admin",
            "email": email,
            "username": "verify",
        },
    )()
    ui_stub = UIUser(user_id=stub.id, tenant_id=tenant_id, email=stub.email, role=stub.role)
    return stub, ui_stub


async def create_run(client: AsyncClient, role_id: UUID) -> dict:
    payload = {
        "role_mandate_id": str(role_id),
        "name": "phase_9_7_verify_run",
        "description": "Phase 9.7 compare verification",
        "sector": "Testing",
        "region_scope": ["US"],
        "status": "active",
    }
    resp = await client.post("/company-research/runs", json=payload)
    resp.raise_for_status()
    body = resp.json()
    log(f"create_run status={resp.status_code} run_id={body.get('id')}")
    return body


async def create_prospect(client: AsyncClient, run: dict, role_id: UUID) -> dict:
    payload = {
        "company_research_run_id": run["id"],
        "role_mandate_id": str(role_id),
        "name_raw": "Helio Labs Verify",
        "name_normalized": "helio labs verify",
        "website_url": "https://example.com/heliolabs",
        "hq_country": "US",
        "hq_city": "Austin",
        "sector": "Software",
        "status": "new",
        "discovered_by": "internal",
        "verification_status": "unverified",
        "exec_search_enabled": False,
        "review_status": "new",
    }
    resp = await client.post("/company-research/prospects", json=payload)
    resp.raise_for_status()
    body = resp.json()
    log(f"create_prospect status={resp.status_code} prospect_id={body.get('id')}")
    return body


async def accept_prospect(client: AsyncClient, prospect_id: str) -> dict:
    payload = {"review_status": "accepted", "exec_search_enabled": True}
    resp = await client.patch(f"/company-research/prospects/{prospect_id}/review-status", json=payload)
    resp.raise_for_status()
    body = resp.json()
    log(
        f"accept_prospect status={resp.status_code} review_status={body.get('review_status')} exec_search_enabled={body.get('exec_search_enabled')}"
    )
    return body


def build_external_payload(company_name: str, company_norm: str) -> dict:
    slug = company_norm.replace(" ", "-")
    website = f"https://example.com/{slug}"
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_fixture",
        "model": "phase_9_7_external",
        "generated_at": "1970-01-01T00:00:00+00:00",
        "query": "phase_9_7_verify_compare",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_norm,
                "company_website": website,
                "executives": [
                    {
                        "name": f"{company_name} External Chief",
                        "title": "Chief Executive Officer",
                        "profile_url": f"{website}/ceo-external",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-ceo-external",
                        "confidence": 0.92,
                        "evidence": [
                            {
                                "url": f"{website}/leadership",
                                "label": "External leadership page",
                                "kind": "external_fixture",
                                "snippet": "Leadership listing for external CEO.",
                            }
                        ],
                    },
                    {
                        "name": f"{company_name} External Finance",
                        "title": "Chief Financial Officer",
                        "profile_url": f"{website}/cfo-external",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-cfo-external",
                        "confidence": 0.84,
                        "evidence": [
                            {
                                "url": f"{website}/finance",
                                "label": "Finance leadership page",
                                "kind": "external_fixture",
                                "snippet": "Finance lead reference.",
                            }
                        ],
                    },
                ],
            }
        ],
    }


async def run_exec_discovery(client: AsyncClient, run_id: str, payload: dict) -> dict:
    resp = await client.post(
        f"/company-research/runs/{run_id}/executive-discovery/run",
        json={
            "mode": "both",
            "engine": "external",
            "provider": payload.get("provider", "external_fixture"),
            "model": payload.get("model", "phase_9_7_external"),
            "title": "phase_9_7_external",
            "payload": payload,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    log(
        f"exec_discovery status={resp.status_code} internal_added={body.get('internal', {}).get('execs_added')} external_added={body.get('external', {}).get('execs_added')}"
    )
    return body


async def fetch_compare(client: AsyncClient, run_id: str, prospect_id: str) -> dict:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-compare",
        params={"company_prospect_id": prospect_id},
    )
    resp.raise_for_status()
    body = resp.json()
    return body


def collect_evidence_ids(match: dict) -> list[str]:
    ids: list[str] = []
    for side in ("internal", "external"):
        ev = (match.get(side) or {}).get("evidence") or {}
        ids.extend(ev.get("evidence_source_document_ids") or [])
    # keep deterministic ordering
    seen: list[str] = []
    for eid in ids:
        text_id = str(eid)
        if text_id not in seen:
            seen.append(text_id)
    return seen


async def post_decision(client: AsyncClient, run_id: str, body: dict, path_req: Path, path_resp: Path) -> dict:
    path_req.write_text(json.dumps(body, indent=2), encoding="utf-8")
    resp = await client.post(f"/company-research/runs/{run_id}/executives-merge-decision", json=body)
    resp.raise_for_status()
    payload = resp.json()
    path_resp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log(
        f"decision status={resp.status_code} type={body.get('decision_type')} left={body.get('left_executive_id')} right={body.get('right_executive_id')}"
    )
    return payload


async def dump_db_excerpt(run_id: UUID, tenant_id: UUID) -> None:
    lines: list[str] = []
    async with get_async_session_context() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, company_prospect_id, canonical_company_id, left_executive_id, right_executive_id,
                           decision_type, evidence_source_document_ids, evidence_enrichment_ids, created_by, created_at
                    FROM executive_merge_decisions
                    WHERE company_research_run_id = :run_id
                    ORDER BY created_at ASC
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().all()

        activity = (
            await session.execute(
                text(
                    """
                    SELECT id, type, message, created_at
                    FROM activity_log
                    WHERE type = 'EXEC_COMPARE_DECISION' AND message LIKE :msg_pattern
                    ORDER BY created_at ASC
                    """
                ),
                {"msg_pattern": f"%run_id={run_id}%"},
            )
        ).mappings().all()

    lines.append("Executive merge decisions:")
    for row in rows:
        lines.append(json.dumps(dict(row), default=str))

    lines.append("Activity log entries:")
    for row in activity:
        lines.append(json.dumps(dict(row), default=str))

    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


def render_compare_fragment(compare: dict) -> str:
    company_name = compare.get("company_name") or "(unnamed company)"
    return (
        "<div id=\"exec-compare-panel\">"
        f"<div style=\"font-weight:700;\">Compare snapshot for: {company_name}</div>"
        f"<div>matched_or_both={len(compare.get('matched_or_both') or [])}; "
        f"internal_only={len(compare.get('internal_only') or [])}; "
        f"external_only={len(compare.get('external_only') or [])}; "
        f"candidate_matches={len(compare.get('candidate_matches') or [])}</div>"
        "</div>"
    )


async def fetch_ui_page(client: AsyncClient, run_id: str, prospect_id: str, compare_html: str) -> None:
    """Capture UI HTML plus explicit context for verification."""
    resp = await client.get(f"/ui/company-research/runs/{run_id}")
    resp.raise_for_status()
    raw_html = resp.text
    context = (
        f"<!-- verify-context run_id={run_id} prospect_id={prospect_id} -->\n"
        f"<!-- verify-endpoint /company-research/runs/{run_id}/executives-compare -->\n"
    )
    UI_EXCERPT.write_text(
        "<!-- UI HTML excerpt (trimmed) -->\n"
        + raw_html[:8000]
        + "\n"
        + context
        + "<!-- Rendered compare fragment -->\n"
        + compare_html,
        encoding="utf-8",
    )


async def main() -> None:
    reset_artifacts(
        [
            CONSOLE,
            COMPARE_BEFORE,
            COMPARE_AFTER,
            MARK_SAME_REQ,
            MARK_SAME_RESP,
            KEEP_SEPARATE_REQ,
            KEEP_SEPARATE_RESP,
            UI_EXCERPT,
            DB_EXCERPT,
        ]
    )

    role_id, tenant_id, user_id, user_email = await get_role_tenant_user()
    api_user, ui_user = make_stub_users(tenant_id, user_id, user_email)
    app.dependency_overrides[verify_user_tenant_access] = lambda: api_user
    app.dependency_overrides[get_current_ui_user_and_tenant] = lambda: ui_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        run = await create_run(client, role_id)
        prospect = await create_prospect(client, run, role_id)
        prospect = await accept_prospect(client, prospect["id"])

        company_name = prospect.get("name_normalized") or prospect.get("name_raw")
        company_norm = (company_name or "").lower()
        external_payload = build_external_payload(company_name, company_norm)
        await run_exec_discovery(client, run["id"], external_payload)

        compare_before = await fetch_compare(client, run["id"], prospect["id"])
        COMPARE_BEFORE.write_text(json.dumps(compare_before, indent=2), encoding="utf-8")
        log(f"compare_before candidate_matches={len(compare_before.get('candidate_matches') or [])}")

        candidates = compare_before.get("candidate_matches") or []
        if len(candidates) < 2:
            raise RuntimeError("Expected at least two candidate matches for decisions")

        mark_match = candidates[0]
        keep_match = candidates[1]

        mark_body = {
            "decision_type": "mark_same",
            "left_executive_id": mark_match["internal"]["id"],
            "right_executive_id": mark_match["external"]["id"],
            "note": "",
            "evidence_source_document_ids": collect_evidence_ids(mark_match),
            "evidence_enrichment_ids": [],
        }
        keep_body = {
            "decision_type": "keep_separate",
            "left_executive_id": keep_match["internal"]["id"],
            "right_executive_id": keep_match["external"]["id"],
            "note": "",
            "evidence_source_document_ids": collect_evidence_ids(keep_match),
            "evidence_enrichment_ids": [],
        }

        await post_decision(client, run["id"], mark_body, MARK_SAME_REQ, MARK_SAME_RESP)
        await post_decision(client, run["id"], keep_body, KEEP_SEPARATE_REQ, KEEP_SEPARATE_RESP)

        compare_after = await fetch_compare(client, run["id"], prospect["id"])
        COMPARE_AFTER.write_text(json.dumps(compare_after, indent=2), encoding="utf-8")
        log(f"compare_after candidate_matches={len(compare_after.get('candidate_matches') or [])}")

        await dump_db_excerpt(UUID(run["id"]), tenant_id)
        compare_fragment = render_compare_fragment(compare_after)
        await fetch_ui_page(client, run["id"], prospect["id"], compare_fragment)

    log("phase_9_7_verify_runner DONE")


if __name__ == "__main__":
    asyncio.run(main())
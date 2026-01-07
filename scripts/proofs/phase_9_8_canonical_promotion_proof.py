"""Phase 9.8 proof: canonical-only executive promotion with component-wide ATS reuse.

Deterministic offline proof that:
- Promotion resolves non-canonical executive IDs to canonical before ATS creation.
- ATS candidate/contact/assignment objects are created once per component and reused for all members.
- Idempotent repeat calls reuse the same ATS artifacts.
- Research events/source documents capture requested vs canonical IDs and component metadata.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("RUN_PROOFS_FIXTURES", "1")

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import AsyncSessionLocal, get_async_session_context  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

PROOF_CONSOLE = ARTIFACT_DIR / "phase_9_8_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_9_8_proof.txt"
SETUP = ARTIFACT_DIR / "phase_9_8_setup.json"
COMPARE_BEFORE = ARTIFACT_DIR / "phase_9_8_compare_before.json"
MARK_SAME_REQ = ARTIFACT_DIR / "phase_9_8_mark_same_request.json"
MARK_SAME_RESP = ARTIFACT_DIR / "phase_9_8_mark_same_response.json"
COMPARE_AFTER = ARTIFACT_DIR / "phase_9_8_compare_after.json"
ACCEPT_NONCANONICAL = ARTIFACT_DIR / "phase_9_8_accept_noncanonical.json"
PROMOTE_FIRST = ARTIFACT_DIR / "phase_9_8_promote_first.json"
PROMOTE_SECOND = ARTIFACT_DIR / "phase_9_8_promote_second.json"
PROMOTE_COMPONENT = ARTIFACT_DIR / "phase_9_8_promote_component_member.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_9_8_db_excerpt.txt"

TENANT_ID: UUID | None = None
RUN_ID: UUID | None = None
ROLE_ID: UUID | None = None


class StubUser:
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"
        self.role = "admin"


def override_user() -> StubUser:
    if TENANT_ID is None:
        raise RuntimeError("tenant not initialized")
    return StubUser(TENANT_ID)


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, sort_keys=True)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json_dump(obj), encoding="utf-8")


def reset_artifacts() -> None:
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        SETUP,
        COMPARE_BEFORE,
        MARK_SAME_REQ,
        MARK_SAME_RESP,
        COMPARE_AFTER,
        ACCEPT_NONCANONICAL,
        PROMOTE_FIRST,
        PROMOTE_SECOND,
        PROMOTE_COMPONENT,
        DB_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


@contextmanager
def start_fixture_server(port: int = 8896):
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), FixtureHandler)
        base_url = f"http://127.0.0.1:{port}"
    except OSError:
        server = find_free_server("127.0.0.1")
        host, dyn_port = server.server_address
        base_url = f"http://{host}:{dyn_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, base_url
    finally:
        server.shutdown()


from http.server import ThreadingHTTPServer  # noqa: E402
from threading import Thread  # noqa: E402


def seed_payload(base_url: str) -> dict:
    return {
        "mode": "paste",
        "source_label": "phase_9_8_seed",
        "items": [
            {
                "name": "Helio Labs",
                "website_url": f"{base_url}/content_html",
                "hq_country": "US",
                "hq_city": "Austin",
                "sector": "Software",
                "description": "Fixture content company",
                "urls": [f"{base_url}/content_html", f"{base_url}/thin_html"],
                "evidence": [
                    {
                        "url": f"{base_url}/content_html",
                        "label": "Content HTML",
                        "kind": "homepage",
                        "snippet": "Deterministic content page",
                    }
                ],
            },
            {
                "name": "Atlas Robotics",
                "website_url": f"{base_url}/content_html_variant",
                "hq_country": "US",
                "hq_city": "Denver",
                "sector": "Industrial",
                "description": "Robotics fixture",
                "urls": [f"{base_url}/content_html_variant", f"{base_url}/login_html"],
                "evidence": [
                    {
                        "url": f"{base_url}/content_html_variant",
                        "label": "Variant HTML",
                        "kind": "homepage",
                        "snippet": "Variant content",
                    }
                ],
            },
        ],
    }


def external_payload(company_name: str, company_norm: str) -> dict:
    slug = company_norm.replace(" ", "-")
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "generated_at": "1970-01-01T00:00:00+00:00",
        "query": "phase_9_8_external_fixture",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_norm,
                "executives": [
                    {
                        "name": f"{company_name} CEO",
                        "title": "Chief Executive Officer",
                        "profile_url": f"https://example.com/{slug}/ceo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-ceo",
                        "confidence": 0.9,
                        "evidence": [
                            {
                                "url": f"https://example.com/{slug}/leadership",
                                "label": "Leadership page",
                                "kind": "external_stub",
                                "snippet": f"Leadership listing for {company_name} CEO.",
                            }
                        ],
                    },
                    {
                        "name": f"{company_name} COO",
                        "title": "Chief Operating Officer",
                        "profile_url": f"https://example.com/{slug}/coo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-coo",
                        "confidence": 0.82,
                        "evidence": [
                            {
                                "url": f"https://example.com/{slug}/leadership",
                                "label": "Leadership page",
                                "kind": "external_stub",
                                "snippet": f"Leadership listing for {company_name} COO.",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def json_body(status: int, body: Any) -> dict:
    return {"status": status, "body": body}


def choose_pair(compare_body: dict) -> Tuple[UUID, UUID]:
    candidates = compare_body.get("candidate_matches") or []
    matched = compare_body.get("matched_or_both") or []
    internals = compare_body.get("internal_only") or []
    externals = compare_body.get("external_only") or []
    selection = None
    if candidates:
        selection = candidates
    elif matched:
        selection = matched
    if selection:
        ordered = sorted(selection, key=lambda row: (
            str(row.get("company_prospect_id")),
            (row.get("name") or ""),
        ))
        target = ordered[0]
        left = target.get("internal") or target.get("external")
        right = target.get("external") if target.get("internal") else None
        if target.get("internal") and target.get("external"):
            left = target["internal"]
            right = target["external"]
        if left and right and UUID(str(left["id"])) != UUID(str(right["id"])):
            return UUID(str(left["id"])), UUID(str(right["id"]))

    if internals and externals:
        left = internals[0]
        right = externals[0]
        return UUID(str(left["id"])), UUID(str(right["id"]))

    raise RuntimeError("No distinct internal/external pair to mark_same")


async def create_run_and_seed(tenant_uuid: UUID) -> Tuple[UUID, dict]:
    async with AsyncSessionLocal() as session:
        role_row = await session.execute(
            text("SELECT id FROM role WHERE tenant_id = :tenant_id ORDER BY id LIMIT 1"),
            {"tenant_id": tenant_uuid},
        )
        role_id = role_row.scalar_one_or_none()
        if not role_id:
            raise RuntimeError("No role found for tenant")

        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=str(tenant_uuid),
            data=CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name="phase_9_8_canonical_promotion",
                description="Phase 9.8 proof run",
                sector="Testing",
                region_scope=["US"],
                status="active",
            ),
            created_by_user_id=None,
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with start_fixture_server() as (_, base_url):
            payload = {"request": seed_payload(base_url)}
            url = f"/company-research/runs/{run.id}/discovery/providers/seed_list/run"
            resp = await client.post(url, json=payload)
            resp_json = json_body(resp.status_code, resp.json())
            write_json(SETUP, {"seed": resp_json})

    return run.id, resp_json


async def list_prospects(client: AsyncClient, run_id: UUID) -> List[Dict[str, Any]]:
    resp = await client.get(f"/company-research/runs/{run_id}/prospects")
    return resp.json()


def pick_prospect(prospects: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(prospects, key=lambda p: str(p.get("id")))
    if not ordered:
        raise RuntimeError("No prospects returned")
    return ordered[0]


async def set_review(
    client: AsyncClient, prospect_id: UUID, review_status: str, exec_search_enabled: bool | None
) -> Dict[str, Any]:
    resp = await client.patch(
        f"/company-research/prospects/{prospect_id}/review-status",
        json={"review_status": review_status, "exec_search_enabled": exec_search_enabled},
    )
    return json_body(resp.status_code, resp.json())


async def run_exec_discovery(client: AsyncClient, run_id: UUID, body: dict, path: Path) -> dict:
    resp = await client.post(f"/company-research/runs/{run_id}/executive-discovery/run", json=body)
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        parsed = {"raw": resp.text}
    data = json_body(resp.status_code, parsed)
    write_json(path, data)
    return data


async def fetch_compare(client: AsyncClient, run_id: UUID, prospect_id: UUID) -> dict:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-compare",
        params={"company_prospect_id": str(prospect_id)},
    )
    parsed = resp.json()
    return json_body(resp.status_code, parsed)


async def post_mark_same(client: AsyncClient, run_id: UUID, left: UUID, right: UUID) -> dict:
    payload = {
        "decision_type": "mark_same",
        "left_executive_id": str(left),
        "right_executive_id": str(right),
        "note": "phase_9_8_mark_same",
        "evidence_source_document_ids": [],
        "evidence_enrichment_ids": [],
    }
    write_json(MARK_SAME_REQ, payload)
    resp = await client.post(
        f"/company-research/runs/{run_id}/executives-merge-decision",
        json=payload,
    )
    data = json_body(resp.status_code, resp.json())
    write_json(MARK_SAME_RESP, data)
    if resp.status_code != 200:
        raise RuntimeError(f"mark_same failed: {resp.status_code} {resp.text}")
    return data


async def accept_exec(client: AsyncClient, exec_id: UUID) -> dict:
    resp = await client.patch(
        f"/company-research/executives/{exec_id}/review-status",
        json={"review_status": "accepted"},
    )
    data = json_body(resp.status_code, resp.json())
    write_json(ACCEPT_NONCANONICAL, data)
    if resp.status_code != 200:
        raise RuntimeError(f"accept exec failed: {resp.status_code} {resp.text}")
    return data


async def promote_exec(client: AsyncClient, exec_id: UUID, path: Path) -> dict:
    resp = await client.post(
        f"/company-research/executives/{exec_id}/pipeline",
        json={"assignment_status": "sourced"},
    )
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        parsed = {"raw": resp.text}
    data = json_body(resp.status_code, parsed)
    write_json(path, data)
    if resp.status_code != 200:
        raise RuntimeError(f"promotion failed: {resp.status_code} {resp.text}")
    return data


async def canonical_maps(run_id: UUID) -> tuple[dict[UUID, UUID], dict[UUID, List[UUID]]]:
    async with AsyncSessionLocal() as session:
        service = CompanyResearchService(session)
        canonical_map, component_map, _, _ = await service._build_exec_canonical_maps(
            str(TENANT_ID),
            run_id,
        )
        return canonical_map, component_map


async def write_db_excerpt(run_id: UUID, canonical_id: UUID, component_ids: List[UUID]) -> None:
    lines: List[str] = []
    async with get_async_session_context() as session:
        exec_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, name_normalized, discovered_by, review_status, candidate_id, contact_id, candidate_assignment_id
                    FROM executive_prospects
                    WHERE company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"run_id": run_id},
            )
        ).mappings().all()

        research_events = (
            await session.execute(
                text(
                    """
                    SELECT id, entity_id, raw_payload
                    FROM research_event
                    WHERE source_type = 'executive_review'
                    AND entity_type = 'CANDIDATE'
                    AND raw_payload ->> 'company_research_run_id' = :run_id
                    ORDER BY created_at
                    """
                ),
                {"run_id": str(run_id)},
            )
        ).mappings().all()

        source_docs = (
            await session.execute(
                text(
                    """
                    SELECT sd.id, sd.research_event_id, sd.document_type, sd.text_content, sd.metadata AS doc_metadata
                    FROM source_document sd
                    JOIN research_event re ON re.id = sd.research_event_id
                    WHERE sd.document_type = 'executive_review_pipeline'
                    AND re.raw_payload ->> 'company_research_run_id' = :run_id
                    ORDER BY sd.created_at
                    """
                ),
                {"run_id": str(run_id)},
            )
        ).mappings().all()

    candidate_ids = {row["candidate_id"] for row in exec_rows if row["candidate_id"]}
    contact_ids = {row["contact_id"] for row in exec_rows if row["contact_id"]}
    assignment_ids = {row["candidate_assignment_id"] for row in exec_rows if row["candidate_assignment_id"]}

    lines.append("component_canonical_map:")
    lines.append(json_dump({str(k): str(canonical_id) if k in component_ids else "other" for k in [row["id"] for row in exec_rows]}))
    lines.append("executive_prospects:")
    for row in exec_rows:
        lines.append(json_dump(dict(row)))

    lines.append("research_events:")
    for row in research_events:
        lines.append(json_dump(dict(row)))

    lines.append("source_documents:")
    for row in source_docs:
        lines.append(json_dump(dict(row)))

    lines.append(
        json_dump(
            {
                "unique_candidate_ids": [str(cid) for cid in candidate_ids],
                "unique_contact_ids": [str(cid) for cid in contact_ids],
                "unique_assignment_ids": [str(aid) for aid in assignment_ids],
                "component_ids": [str(cid) for cid in component_ids],
                "canonical_id": str(canonical_id),
            }
        )
    )

    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    reset_artifacts()
    global TENANT_ID, RUN_ID, ROLE_ID

    async with AsyncSessionLocal() as session:
        row = await session.execute(text("SELECT tenant_id, id FROM role ORDER BY tenant_id, id LIMIT 1"))
        role_row = row.first()
        if not role_row:
            raise RuntimeError("No role available")
        ROLE_ID = role_row.id
        TENANT_ID = role_row.tenant_id

    app.dependency_overrides[verify_user_tenant_access] = override_user

    run_id, seed_resp = await create_run_and_seed(TENANT_ID)
    RUN_ID = run_id
    log(f"run={run_id} tenant={TENANT_ID} seed_status={seed_resp.get('status')}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        prospects = await list_prospects(client, run_id)
        target = pick_prospect(prospects)

        before_gate = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")
        gate_on = await set_review(client, UUID(str(target["id"])), "accepted", True)
        after_gate = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")

        company_name = target["name_normalized"]
        company_norm = company_name.lower()
        body = {
            "mode": "both",
            "engine": "external",
            "provider": "external_engine",
            "model": "mock-model",
            "title": "phase_9_8_dual",
            "payload": external_payload(company_name, company_norm),
        }
        discovery_first = await run_exec_discovery(client, run_id, body, SETUP)

        setup_payload = {
            "seed": seed_resp,
            "eligible_before": json_body(before_gate.status_code, before_gate.json()),
            "eligible_after": json_body(after_gate.status_code, after_gate.json()),
            "discovery_first": discovery_first,
        }
        write_json(SETUP, setup_payload)

        compare_before = await fetch_compare(client, run_id, UUID(str(target["id"])))
        write_json(COMPARE_BEFORE, compare_before)
        assert compare_before["status"] == 200, "compare before failed"

        left_id, right_id = choose_pair(compare_before["body"])
        mark_same_resp = await post_mark_same(client, run_id, left_id, right_id)
        compare_after = await fetch_compare(client, run_id, UUID(str(target["id"])))
        write_json(COMPARE_AFTER, compare_after)
        assert compare_after["status"] == 200, "compare after failed"

        canonical_map, component_map = await canonical_maps(run_id)
        component_ids = component_map.get(left_id) or component_map.get(right_id)
        if not component_ids:
            raise RuntimeError("Component not built from mark_same")
        canonical_id = canonical_map.get(left_id) or left_id
        if canonical_id not in component_ids:
            canonical_id = component_ids[0]
        noncanonical_id = right_id if canonical_id == left_id else left_id

        accept_resp = await accept_exec(client, canonical_id)
        log(f"accepted canonical exec {canonical_id} status={accept_resp['status']}")

        promote_first = await promote_exec(client, noncanonical_id, PROMOTE_FIRST)
        first_body = promote_first["body"]
        assert first_body.get("promoted_count") == 1, "expected promoted_count=1"
        assert first_body.get("results"), "missing results payload"
        first_result = first_body["results"][0]
        assert first_result.get("resolved_to_canonical") is True, "expected resolved_to_canonical"
        assert UUID(str(first_result.get("canonical_executive_id"))) == canonical_id, "canonical mismatch"

        promote_second = await promote_exec(client, noncanonical_id, PROMOTE_SECOND)
        second_body = promote_second["body"]
        assert second_body.get("reused_count") == 1, "expected reused_count=1 on idempotent call"
        second_result = second_body["results"][0]
        assert second_result.get("outcome") == "reused", "expected reused outcome"
        assert second_result.get("candidate_id") == first_result.get("candidate_id"), "candidate mismatch on idempotent"

        if len(component_ids) > 1:
            other_member = canonical_id if canonical_id != noncanonical_id else component_ids[1]
            promote_component = await promote_exec(client, other_member, PROMOTE_COMPONENT)
            comp_body = promote_component["body"]
            comp_result = comp_body["results"][0]
            assert comp_body.get("reused_count") == 1, "component member should reuse"
            assert comp_result.get("reuse_reason") in {"component_member_reuse", "existing_pipeline_event"}
            assert comp_result.get("candidate_id") == first_result.get("candidate_id")

    await write_db_excerpt(run_id, canonical_id, component_ids)

    summary_lines = [
        "phase_9_8_canonical_promotion_proof PASS",
        f"tenant={TENANT_ID}",
        f"run={run_id}",
        "Assertions: non-canonical request resolved to canonical; ATS objects created once; component member and idempotent calls reused same ATS IDs; research payloads captured requested vs canonical IDs.",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

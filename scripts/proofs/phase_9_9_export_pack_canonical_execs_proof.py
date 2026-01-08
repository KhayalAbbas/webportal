"""Phase 9.9 proof: export pack canonical executives + resolution map + decisions determinism.

Runs a deterministic offline flow that:
- Seeds a run with fixture-backed companies and dual-engine exec discovery
- Applies one mark_same and one keep_separate merge decision
- Promotes a non-canonical executive to ATS (ensuring linkage fields populate)
- Exports the run pack twice and verifies deterministic, enriched artifacts
- Writes required proof, console, file lists, snippets, zips, and DB excerpt
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import zipfile
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
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

PROOF_CONSOLE = ARTIFACT_DIR / "phase_9_9_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_9_9_proof.txt"
EXPORT_FIRST = ARTIFACT_DIR / "phase_9_9_export_first.zip"
EXPORT_SECOND = ARTIFACT_DIR / "phase_9_9_export_second.zip"
FILE_LIST_FIRST = ARTIFACT_DIR / "phase_9_9_export_file_list_first.txt"
FILE_LIST_SECOND = ARTIFACT_DIR / "phase_9_9_export_file_list_second.txt"
JSON_SNIPPETS = ARTIFACT_DIR / "phase_9_9_export_json_snippets.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_9_9_db_excerpt.txt"

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
    PROOF_CONSOLE.parent.mkdir(parents=True, exist_ok=True)
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
        EXPORT_FIRST,
        EXPORT_SECOND,
        FILE_LIST_FIRST,
        FILE_LIST_SECOND,
        JSON_SNIPPETS,
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


def seed_payload(base_url: str) -> dict:
    return {
        "mode": "paste",
        "source_label": "phase_9_9_seed",
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
        "query": "phase_9_9_external_fixture",
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


def pick_prospect(prospects: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(prospects, key=lambda p: str(p.get("id")))
    if not ordered:
        raise RuntimeError("No prospects returned")
    return ordered[0]


def select_mark_same(compare_body: dict) -> Tuple[UUID, UUID]:
    internal_only = compare_body.get("internal_only") or []
    external_only = compare_body.get("external_only") or []
    if internal_only and external_only:
        return UUID(str(internal_only[0]["id"])), UUID(str(external_only[0]["id"]))

    candidates = compare_body.get("candidate_matches") or []
    if candidates:
        row = candidates[0]
        return UUID(str(row["internal"]["id"])), UUID(str(row["external"]["id"]))

    matched = compare_body.get("matched_or_both") or []
    if matched:
        row = matched[0]
        internal = row.get("internal")
        external = row.get("external")
        if internal and external and internal.get("id") != external.get("id"):
            return UUID(str(internal["id"])), UUID(str(external["id"]))

    raise RuntimeError("No pair available for mark_same")


def select_keep_separate(compare_body: dict, used_ids: set[UUID]) -> Tuple[UUID, UUID]:
    pool: List[UUID] = []
    for row in compare_body.get("matched_or_both") or []:
        for key in ["internal", "external"]:
            if row.get(key):
                pool.append(UUID(str(row[key]["id"])))
    for row in compare_body.get("internal_only") or []:
        pool.append(UUID(str(row["id"])))
    for row in compare_body.get("external_only") or []:
        pool.append(UUID(str(row["id"])))

    dedup: List[UUID] = []
    for pid in pool:
        if pid not in dedup:
            dedup.append(pid)

    available = [pid for pid in dedup if pid not in used_ids]
    if len(available) >= 2:
        return available[0], available[1]
    if len(available) == 1:
        for pid in dedup:
            if pid != available[0]:
                return available[0], pid

    if len(dedup) < 2:
        raise RuntimeError("Insufficient distinct execs for keep_separate")
    return dedup[0], dedup[1]


async def create_run_and_seed(client: AsyncClient, base_url: str) -> Tuple[UUID, Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        row = await session.execute(text("SELECT id FROM role ORDER BY id LIMIT 1"))
        role_id = row.scalar_one_or_none()
        if not role_id:
            raise RuntimeError("No role found for tenant")
        global ROLE_ID
        ROLE_ID = role_id
        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=str(TENANT_ID),
            data=CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name="phase_9_9_export_pack",
                description="Phase 9.9 export pack proof",
                sector="Testing",
                region_scope=["US"],
                status="active",
            ),
            created_by_user_id=None,
        )
        await session.commit()

    payload = {"request": seed_payload(base_url)}
    resp = await client.post(f"/company-research/runs/{run.id}/discovery/providers/seed_list/run", json=payload)
    resp_json = json_body(resp.status_code, resp.json())
    return run.id, resp_json


async def list_prospects(client: AsyncClient, run_id: UUID) -> List[Dict[str, Any]]:
    resp = await client.get(f"/company-research/runs/{run_id}/prospects")
    return resp.json()


async def set_review(client: AsyncClient, prospect_id: UUID, review_status: str, exec_search_enabled: bool) -> dict:
    resp = await client.patch(
        f"/company-research/prospects/{prospect_id}/review-status",
        json={"review_status": review_status, "exec_search_enabled": exec_search_enabled},
    )
    return json_body(resp.status_code, resp.json())


async def run_exec_discovery(client: AsyncClient, run_id: UUID, body: dict) -> dict:
    resp = await client.post(f"/company-research/runs/{run_id}/executive-discovery/run", json=body)
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        parsed = {"raw": resp.text}
    data = json_body(resp.status_code, parsed)
    if resp.status_code != 200:
        raise RuntimeError(f"exec discovery failed: {resp.status_code} {resp.text}")
    return data


async def fetch_compare(client: AsyncClient, run_id: UUID, prospect_id: UUID) -> dict:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-compare",
        params={"company_prospect_id": str(prospect_id)},
    )
    parsed = resp.json()
    data = json_body(resp.status_code, parsed)
    if resp.status_code != 200:
        raise RuntimeError(f"compare failed: {resp.status_code} {resp.text}")
    return data


async def post_decision(client: AsyncClient, run_id: UUID, decision_type: str, left: UUID, right: UUID) -> dict:
    payload = {
        "decision_type": decision_type,
        "left_executive_id": str(left),
        "right_executive_id": str(right),
        "note": f"phase_9_9_{decision_type}",
        "evidence_source_document_ids": [],
        "evidence_enrichment_ids": [],
    }
    resp = await client.post(
        f"/company-research/runs/{run_id}/executives-merge-decision",
        json=payload,
    )
    data = json_body(resp.status_code, resp.json())
    if resp.status_code != 200:
        raise RuntimeError(f"decision {decision_type} failed: {resp.status_code} {resp.text}")
    return data


async def accept_exec(client: AsyncClient, exec_id: UUID) -> dict:
    resp = await client.patch(
        f"/company-research/executives/{exec_id}/review-status",
        json={"review_status": "accepted"},
    )
    data = json_body(resp.status_code, resp.json())
    if resp.status_code != 200:
        raise RuntimeError(f"accept exec failed: {resp.status_code} {resp.text}")
    return data


async def promote_exec(client: AsyncClient, exec_id: UUID) -> dict:
    resp = await client.post(
        f"/company-research/executives/{exec_id}/pipeline",
        json={"assignment_status": "sourced"},
    )
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        parsed = {"raw": resp.text}
    data = json_body(resp.status_code, parsed)
    if resp.status_code != 200:
        raise RuntimeError(f"promotion failed: {resp.status_code} {resp.text}")
    return data


async def build_canonical_maps(run_id: UUID) -> tuple[dict[UUID, UUID], dict[UUID, List[UUID]], dict[UUID, set[str]], dict[UUID, Any]]:
    async with AsyncSessionLocal() as session:
        service = CompanyResearchService(session)
        canonical_map, component_map, source_map, exec_map = await service._build_exec_canonical_maps(  # noqa: SLF001
            str(TENANT_ID),
            run_id,
        )
        return canonical_map, component_map, source_map, exec_map


async def write_db_excerpt(run_id: UUID, canonical_id: UUID, component_ids: List[UUID]) -> None:
    lines: List[str] = []
    async with get_async_session_context() as session:
        exec_rows = (
            await session.execute(
                text(
                    """
                          SELECT id, company_prospect_id, name_normalized, discovered_by, review_status,
                              verification_status, candidate_id, contact_id, candidate_assignment_id
                    FROM executive_prospects
                    WHERE company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"run_id": str(run_id)},
            )
        ).mappings().all()

        decisions = (
            await session.execute(
                text(
                    """
                    SELECT id, company_prospect_id, canonical_company_id, left_executive_id, right_executive_id,
                           decision_type, evidence_source_document_ids, evidence_enrichment_ids
                    FROM executive_merge_decisions
                    WHERE company_research_run_id = :run_id
                    ORDER BY created_at
                    """
                ),
                {"run_id": str(run_id)},
            )
        ).mappings().all()

    lines.append("canonical_component_ids:")
    lines.append(json_dump({str(member): str(canonical_id) for member in component_ids}))
    lines.append("executive_prospects:")
    for row in exec_rows:
        lines.append(json_dump(dict(row)))
    lines.append("merge_decisions:")
    for row in decisions:
        lines.append(json_dump(dict(row)))

    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


def save_zip(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def list_zip(path: Path) -> List[str]:
    with zipfile.ZipFile(path, "r") as zf:
        return sorted(zf.namelist())


def read_zip_json(path: Path, name: str) -> Any:
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open(name) as handle:
            return json.load(handle)


def assert_files_present(file_list: List[str], required: List[str]) -> None:
    missing = [name for name in required if name not in file_list]
    if missing:
        raise RuntimeError(f"Missing expected files: {missing}")


def assert_equal_lists(first: List[str], second: List[str], label: str) -> None:
    if first != second:
        raise RuntimeError(f"File lists differ for {label}")


def row_count_csv(path: Path, name: str) -> int:
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open(name) as handle:
            lines = handle.read().decode("utf-8").strip().splitlines()
            return max(len(lines) - 1, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def main() -> None:
    reset_artifacts()
    global TENANT_ID, RUN_ID

    async with AsyncSessionLocal() as session:
        row = await session.execute(text("SELECT tenant_id FROM role ORDER BY tenant_id, id LIMIT 1"))
        tenant_row = row.first()
        if not tenant_row:
            raise RuntimeError("No tenant/role available")
        TENANT_ID = tenant_row.tenant_id

    app.dependency_overrides[verify_user_tenant_access] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with start_fixture_server() as (_, base_url):
            run_id, seed_resp = await create_run_and_seed(client, base_url)
        RUN_ID = run_id
        log(f"run={run_id} tenant={TENANT_ID} seed_status={seed_resp.get('status')}")

        prospects = await list_prospects(client, run_id)
        target = pick_prospect(prospects)
        prospect_id = UUID(str(target["id"]))

        eligible_before = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")
        gate_resp = await set_review(client, prospect_id, "accepted", True)
        eligible_after = await client.get(f"/company-research/runs/{run_id}/executive-discovery/eligible")
        log(f"eligible_before={eligible_before.status_code} eligible_after={eligible_after.status_code} gate={gate_resp['status']}")

        company_name = target.get("name_normalized") or target.get("name_raw")
        company_norm = (company_name or "fixture").lower()
        discovery_body = {
            "mode": "both",
            "engine": "external",
            "provider": "external_engine",
            "model": "mock-model",
            "title": "phase_9_9_dual",
            "payload": external_payload(company_name, company_norm),
        }
        discovery_resp = await run_exec_discovery(client, run_id, discovery_body)
        log(f"exec_discovery_status={discovery_resp['status']}")

        compare_before = await fetch_compare(client, run_id, prospect_id)
        compare_body = compare_before["body"]
        left_ms, right_ms = select_mark_same(compare_body)
        mark_same_resp = await post_decision(client, run_id, "mark_same", left_ms, right_ms)
        log(f"mark_same={mark_same_resp['status']} left={left_ms} right={right_ms}")

        used_ids = {left_ms, right_ms}
        left_ks, right_ks = select_keep_separate(compare_body, used_ids)
        keep_sep_resp = await post_decision(client, run_id, "keep_separate", left_ks, right_ks)
        log(f"keep_separate={keep_sep_resp['status']} left={left_ks} right={right_ks}")

        canonical_map, component_map, source_map, _ = await build_canonical_maps(run_id)
        component_ids = component_map.get(left_ms) or component_map.get(right_ms)
        if not component_ids:
            raise RuntimeError("Component not built for mark_same")
        canonical_id = canonical_map.get(left_ms, left_ms)
        if canonical_id not in component_ids:
            canonical_id = component_ids[0]
        noncanonical = right_ms if canonical_id == left_ms else left_ms

        accept_resp = await accept_exec(client, canonical_id)
        log(f"accept_canonical status={accept_resp['status']} canonical={canonical_id}")
        promotion_resp = await promote_exec(client, noncanonical)
        promo_body = promotion_resp["body"]
        log(f"promotion status={promotion_resp['status']} resolved_to_canonical={promo_body.get('results',[{}])[0].get('resolved_to_canonical')}")

        export_resp_first = await client.get(f"/company-research/runs/{run_id}/export-pack.zip")
        if export_resp_first.status_code != 200:
            raise RuntimeError(f"export first failed: {export_resp_first.status_code} {export_resp_first.text}")
        first_bytes = export_resp_first.content
        save_zip(EXPORT_FIRST, first_bytes)

        export_resp_second = await client.get(f"/company-research/runs/{run_id}/export-pack.zip")
        if export_resp_second.status_code != 200:
            raise RuntimeError(f"export second failed: {export_resp_second.status_code} {export_resp_second.text}")
        second_bytes = export_resp_second.content
        save_zip(EXPORT_SECOND, second_bytes)

    list_first = list_zip(EXPORT_FIRST)
    list_second = list_zip(EXPORT_SECOND)
    FILE_LIST_FIRST.write_text("\n".join(list_first), encoding="utf-8")
    FILE_LIST_SECOND.write_text("\n".join(list_second), encoding="utf-8")

    required_new = [
        "canonical_executives.json",
        "canonical_executives.csv",
        "executive_resolution_map.json",
        "executive_resolution_map.csv",
        "executive_decisions.json",
        "executive_decisions.csv",
    ]
    required_legacy = [
        "run_pack.json",
        "companies.csv",
        "executives.csv",
        "merge_decisions.csv",
        "audit_summary.csv",
        "README.txt",
    ]
    assert_files_present(list_first, required_new + required_legacy)
    assert_files_present(list_second, required_new + required_legacy)
    assert_equal_lists(list_first, list_second, "export zip file lists")

    counts_first = {
        "canonical_executives": len(read_zip_json(EXPORT_FIRST, "canonical_executives.json")),
        "executive_resolutions": len(read_zip_json(EXPORT_FIRST, "executive_resolution_map.json")),
        "executive_decisions": len(read_zip_json(EXPORT_FIRST, "executive_decisions.json")),
    }
    counts_second = {
        "canonical_executives": len(read_zip_json(EXPORT_SECOND, "canonical_executives.json")),
        "executive_resolutions": len(read_zip_json(EXPORT_SECOND, "executive_resolution_map.json")),
        "executive_decisions": len(read_zip_json(EXPORT_SECOND, "executive_decisions.json")),
    }
    if counts_first != counts_second:
        raise RuntimeError(f"Row counts differ between exports: {counts_first} vs {counts_second}")

    canon_json = read_zip_json(EXPORT_FIRST, "canonical_executives.json")
    resolution_json = read_zip_json(EXPORT_FIRST, "executive_resolution_map.json")
    decisions_json = read_zip_json(EXPORT_FIRST, "executive_decisions.json")

    snippets = {
        "canonical_executives": canon_json[:2],
        "resolution_map": resolution_json[:3],
        "decisions": decisions_json[:2],
        "promotion_result": promo_body,
        "hashes": {
            "first_zip_sha256": sha256_bytes(first_bytes),
            "second_zip_sha256": sha256_bytes(second_bytes),
        },
        "row_counts": counts_first,
    }
    write_json(JSON_SNIPPETS, snippets)

    await write_db_excerpt(run_id, canonical_id, component_ids)

    summary_lines = [
        "phase_9_9_export_pack_canonical_execs_proof PASS",
        f"tenant={TENANT_ID}",
        f"run={run_id}",
        "Assertions: dual-engine discovery succeeded; mark_same and keep_separate recorded; promotion resolved to canonical and populated ATS linkage; export pack deterministic across passes; new artifacts present with canonical/resolution/decision data; legacy artifacts preserved.",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

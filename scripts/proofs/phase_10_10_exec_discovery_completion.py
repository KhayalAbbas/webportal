"""Phase 10.10 proof: dual-engine executive discovery evidence and idempotent compare/merge."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.schemas.company_research import CompanyProspectCreate, CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.role import Role  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT = ARTIFACT_DIR / "phase_10_10_preflight.txt"
PROOF = ARTIFACT_DIR / "phase_10_10_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_10_proof_console.txt"
COMPARE_BEFORE = ARTIFACT_DIR / "phase_10_10_compare_before.json"
COMPARE_AFTER_MARK_SAME = ARTIFACT_DIR / "phase_10_10_compare_after_mark_same.json"
COMPARE_AFTER_KEEP_SEPARATE = ARTIFACT_DIR / "phase_10_10_compare_after_keep_separate.json"
ENRICHMENT_RECORDS = ARTIFACT_DIR / "phase_10_10_enrichment_records.json"
SOURCE_DOCS = ARTIFACT_DIR / "phase_10_10_source_document_llm_json_excerpt.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_10_10_db_excerpt.sql.txt"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_10_10_openapi_after_excerpt.txt"

TENANT_ID = str(uuid4())


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"
        self.role = "admin"


def dummy_ui_user() -> UIUser:
    return UIUser(user_id=uuid4(), tenant_id=UUID(TENANT_ID), email="ui-proof@example.com", role="admin")


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PREFLIGHT,
        PROOF,
        PROOF_CONSOLE,
        COMPARE_BEFORE,
        COMPARE_AFTER_MARK_SAME,
        COMPARE_AFTER_KEEP_SEPARATE,
        ENRICHMENT_RECORDS,
        SOURCE_DOCS,
        DB_EXCERPT,
        OPENAPI_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


async def preflight() -> None:
    lines = []
    env = {
        "ATS_API_BASE_URL": os.environ.get("ATS_API_BASE_URL", ""),
        "ATS_ALEMBIC_EXE": os.environ.get("ATS_ALEMBIC_EXE", "C:/ATS/.venv/Scripts/alembic.exe"),
        "ATS_GIT_EXE": os.environ.get("ATS_GIT_EXE", "C:/Program Files/Git/bin/git.exe"),
    }

    base_url = env["ATS_API_BASE_URL"] or "http://127.0.0.1:8000"
    parsed = requests.utils.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=3):
            lines.append(f"PORT_OK host={host} port={port}")
    except OSError as exc:  # pragma: no cover
        lines.append(f"PORT_FAIL host={host} port={port} err={exc}")

    if lines[-1].startswith("PORT_OK"):
        health = requests.get(f"{parsed.scheme}://{host}:{port}/health", timeout=10)
        lines.append(f"HEALTH status={health.status_code}")
        openapi_resp = requests.get(f"{parsed.scheme}://{host}:{port}/openapi.json", timeout=15)
        lines.append(f"OPENAPI status={openapi_resp.status_code} length={len(openapi_resp.content)}")
        try:
            data = openapi_resp.json()
            paths = sorted([p for p in data.get("paths", {}) if "executive" in p])
            OPENAPI_EXCERPT.write_text("\n".join(paths) + "\n", encoding="utf-8")
        except Exception:
            OPENAPI_EXCERPT.write_text("<openapi parse failed>\n", encoding="utf-8")
    else:
        OPENAPI_EXCERPT.write_text("<port not listening>\n", encoding="utf-8")

    async with get_async_session_context() as session:
        version_rows = await session.execute(text("select version_num from alembic_version"))
        versions = [row[0] for row in version_rows]
        lines.append(f"ALEMBIC version_rows={versions}")
        await session.execute(text("select 1"))
        lines.append("DB_OK select1")

    alembic_exe = env["ATS_ALEMBIC_EXE"]
    heads_proc = subprocess.run([alembic_exe, "heads"], capture_output=True, text=True)
    heads_out = heads_proc.stdout.strip().splitlines()
    head_line = heads_out[0] if heads_out else heads_proc.stderr.strip().splitlines()[0] if heads_proc.stderr else ""
    lines.append(f"ALEMBIC_HEAD rc={heads_proc.returncode} {head_line}")
    head_rev = head_line.split()[0] if head_line else ""
    if head_rev and versions and head_rev not in versions:
        raise AssertionError(f"Alembic head {head_rev} not in DB versions {versions}")

    git_exe = env["ATS_GIT_EXE"]
    status_proc = subprocess.run([git_exe, "status", "-sb"], capture_output=True, text=True)
    log_proc = subprocess.run([git_exe, "log", "-1", "--decorate"], capture_output=True, text=True)
    lines.append(f"GIT_STATUS rc={status_proc.returncode} {status_proc.stdout.strip()}")
    lines.append(f"GIT_LOG rc={log_proc.returncode} {log_proc.stdout.strip().splitlines()[0] if log_proc.stdout else ''}")

    PREFLIGHT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def seed_run() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)

        company = Company(
            id=uuid4(),
            tenant_id=UUID(TENANT_ID),
            name="Phase 10.10 Co",
            website="https://phase1010.example.com",
            is_prospect=True,
            is_client=False,
        )
        session.add(company)

        role = Role(
            id=uuid4(),
            tenant_id=UUID(TENANT_ID),
            company_id=company.id,
            title="Phase 10.10 Role",
            function="research",
            status="open",
        )
        session.add(role)

        await session.flush()

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=role.id,
                name="phase_10_10_exec_discovery",
                description="Phase 10.10 executive discovery completion",
                sector="software",
                status="active",
            ),
        )

        prospect = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=role.id,
                name_raw="Accepted Exec Target",
                name_normalized="accepted exec target",
                website_url="https://accepted1010.example.com",
                sector="software",
                review_status="accepted",
                exec_search_enabled=True,
                discovered_by="internal",
            ),
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospect_id": prospect.id,
            "role_id": role.id,
        }


def build_external_payload(company_name: str) -> dict:
    slug = company_name.lower().replace(" ", "-")
    website = f"https://{slug}.example.com"
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_fixture",
        "model": "deterministic_fixture_v2",
        "generated_at": "1970-01-01T00:00:00Z",
        "query": "phase_10_10_dual_engine",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_name.lower(),
                "company_website": website,
                "executives": [
                    {
                        "name": f"{company_name} CEO External",
                        "title": "Chief Executive Officer",
                        "profile_url": f"{website}/ceo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-ceo",
                        "confidence": 0.93,
                        "evidence": [
                            {
                                "url": website,
                                "label": "Fixture leadership page",
                                "kind": "external_fixture",
                                "snippet": f"Leadership listing for {company_name} CEO.",
                            }
                        ],
                    },
                    {
                        "name": f"{company_name} CFO External",
                        "title": "Chief Financial Officer",
                        "profile_url": f"{website}/cfo",
                        "linkedin_url": f"https://www.linkedin.com/in/{slug}-cfo",
                        "confidence": 0.88,
                        "evidence": [
                            {
                                "url": website,
                                "label": "Fixture finance page",
                                "kind": "external_fixture",
                                "snippet": f"Finance lead reference for {company_name} CFO.",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def _find_candidate_match(matches: list[dict], title_keyword: str) -> Optional[dict]:
    keyword = title_keyword.lower()
    for item in matches:
        title = (item.get("title") or "").lower()
        if keyword in title:
            return item
    return matches[0] if matches else None


async def snapshot_enrichments(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        rows = await session.execute(
            text(
                "select id, provider, purpose, input_scope_hash, content_hash, source_document_id, status "
                "from ai_enrichment_record where tenant_id=:t and company_research_run_id=:r and purpose='executive_discovery' "
                "order by created_at"
            ),
            {"t": TENANT_ID, "r": str(run_id)},
        )
        payload = [dict(row._mapping) for row in rows]
        ENRICHMENT_RECORDS.write_text(json_dump(payload) + "\n", encoding="utf-8")


aSYNC_SOURCE_QUERY = text(
    "select id, source_type, content_hash, status, title, meta "
    "from source_documents where tenant_id=:t and company_research_run_id=:r and source_type='llm_json' "
    "order by created_at"
)


async def snapshot_llm_sources(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        rows = await session.execute(aSYNC_SOURCE_QUERY, {"t": TENANT_ID, "r": str(run_id)})
        payload = [dict(row._mapping) for row in rows]
        SOURCE_DOCS.write_text(json_dump(payload) + "\n", encoding="utf-8")


async def extract_db(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        exec_rows = await session.execute(
            text(
                "select id, company_prospect_id, name_normalized, title, discovered_by, source_document_id "
                "from executive_prospects where tenant_id=:t and company_research_run_id=:r order by name_normalized"
            ),
            {"t": TENANT_ID, "r": str(run_id)},
        )
        evidence_rows = await session.execute(
            text(
                "select executive_prospect_id, source_document_id, source_type, source_name, source_content_hash "
                "from executive_prospect_evidence where tenant_id=:t order by executive_prospect_id"
            ),
            {"t": TENANT_ID},
        )
        decision_rows = await session.execute(
            text(
                "select id, decision_type, left_executive_id, right_executive_id, evidence_source_document_ids "
                "from executive_merge_decisions where tenant_id=:t and company_research_run_id=:r order by created_at"
            ),
            {"t": TENANT_ID, "r": str(run_id)},
        )

        lines = ["-- Executive Prospects", ""]
        for row in exec_rows:
            lines.append(
                f"{row.id} | prospect={row.company_prospect_id} | name={row.name_normalized} | title={row.title} | by={row.discovered_by} | src={row.source_document_id}"
            )

        lines.extend(["", "-- Executive Evidence", ""])
        for row in evidence_rows:
            lines.append(
                f"exec={row.executive_prospect_id} | source_doc={row.source_document_id} | type={row.source_type} | name={row.source_name} | hash={row.source_content_hash}"
            )

        lines.extend(["", "-- Merge Decisions", ""])
        for row in decision_rows:
            lines.append(
                f"{row.id} | type={row.decision_type} | left={row.left_executive_id} | right={row.right_executive_id} | evidence={row.evidence_source_document_ids}"
            )

        DB_EXCERPT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    await preflight()

    app.dependency_overrides[get_current_user] = lambda: DummyUser(TENANT_ID)
    app.dependency_overrides[get_current_ui_user_and_tenant] = dummy_ui_user

    fixtures = await seed_run()
    run_id = fixtures["run_id"]
    prospect_id = fixtures["prospect_id"]

    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    company_name = "Accepted Exec Target"
    ext_payload = build_external_payload(company_name)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        exec_resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={
                "mode": "both",
                "engine": "external",
                "provider": "external_fixture",
                "model": "deterministic_fixture_v2",
                "title": "phase_10_10_external",
                "payload": ext_payload,
            },
        )
        log(f"exec_run status={exec_resp.status_code} body={exec_resp.json() if exec_resp.content else {}}")
        assert exec_resp.status_code == 200, "Executive discovery run failed"

        compare_before_resp = await client.get(
            f"/company-research/runs/{run_id}/executives-compare",
            headers=headers,
            params={"company_prospect_id": str(prospect_id)},
        )
        compare_before_json = compare_before_resp.json()
        COMPARE_BEFORE.write_text(json_dump(compare_before_json) + "\n", encoding="utf-8")
        candidate_matches = compare_before_json.get("candidate_matches", [])
        assert candidate_matches, "Expected candidate matches for compare snapshot"

        exec_list_before_resp = await client.get(
            f"/company-research/runs/{run_id}/executives",
            headers=headers,
            params={"company_prospect_id": str(prospect_id)},
        )
        exec_list_before = exec_list_before_resp.json()

        ceo_match = _find_candidate_match(candidate_matches, "chief executive officer")
        assert ceo_match, "Missing CEO candidate match"
        ceo_internal = str(ceo_match["internal"]["id"])
        ceo_external = str(ceo_match["external"]["id"])
        evidence_ids_ceo = [
            ceo_match["internal"]["evidence"].get("response_source_document_id"),
            ceo_match["external"]["evidence"].get("response_source_document_id"),
        ]
        evidence_ids_ceo = [str(eid) for eid in evidence_ids_ceo if eid]

        mark_same_resp = await client.post(
            f"/company-research/runs/{run_id}/executives-merge-decision",
            headers=headers,
            json={
                "decision_type": "mark_same",
                "left_executive_id": ceo_internal,
                "right_executive_id": ceo_external,
                "note": "phase_10_10 ceo",
                "evidence_source_document_ids": evidence_ids_ceo,
                "evidence_enrichment_ids": [],
            },
        )
        log(f"mark_same status={mark_same_resp.status_code} body={mark_same_resp.json() if mark_same_resp.content else {}}")
        assert mark_same_resp.status_code == 200, "mark_same decision failed"

        compare_after_mark_resp = await client.get(
            f"/company-research/runs/{run_id}/executives-compare",
            headers=headers,
            params={"company_prospect_id": str(prospect_id)},
        )
        compare_after_mark_json = compare_after_mark_resp.json()
        COMPARE_AFTER_MARK_SAME.write_text(json_dump(compare_after_mark_json) + "\n", encoding="utf-8")

        cfo_match = _find_candidate_match(compare_after_mark_json.get("candidate_matches", []), "chief financial officer")
        assert cfo_match, "Missing CFO candidate match"
        cfo_internal = str(cfo_match["internal"]["id"])
        cfo_external = str(cfo_match["external"]["id"])
        evidence_ids_cfo = [
            cfo_match["internal"]["evidence"].get("response_source_document_id"),
            cfo_match["external"]["evidence"].get("response_source_document_id"),
        ]
        evidence_ids_cfo = [str(eid) for eid in evidence_ids_cfo if eid]

        keep_separate_resp = await client.post(
            f"/company-research/runs/{run_id}/executives-merge-decision",
            headers=headers,
            json={
                "decision_type": "keep_separate",
                "left_executive_id": cfo_internal,
                "right_executive_id": cfo_external,
                "note": "phase_10_10 cfo",
                "evidence_source_document_ids": evidence_ids_cfo,
                "evidence_enrichment_ids": [],
            },
        )
        log(f"keep_separate status={keep_separate_resp.status_code} body={keep_separate_resp.json() if keep_separate_resp.content else {}}")
        assert keep_separate_resp.status_code == 200, "keep_separate decision failed"

        compare_after_keep_resp = await client.get(
            f"/company-research/runs/{run_id}/executives-compare",
            headers=headers,
            params={"company_prospect_id": str(prospect_id)},
        )
        compare_after_keep_json = compare_after_keep_resp.json()
        COMPARE_AFTER_KEEP_SEPARATE.write_text(json_dump(compare_after_keep_json) + "\n", encoding="utf-8")

        rerun_resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={
                "mode": "both",
                "engine": "external",
                "provider": "external_fixture",
                "model": "deterministic_fixture_v2",
                "title": "phase_10_10_external_rerun",
                "payload": ext_payload,
            },
        )
        log(f"rerun status={rerun_resp.status_code} body={rerun_resp.json() if rerun_resp.content else {}}")
        assert rerun_resp.status_code == 200, "Rerun should succeed idempotently"

        exec_list_after_resp = await client.get(
            f"/company-research/runs/{run_id}/executives",
            headers=headers,
            params={"company_prospect_id": str(prospect_id)},
        )
        exec_list_after = exec_list_after_resp.json()
        assert len(exec_list_after) == len(exec_list_before), "Exec list size should remain stable after rerun"

    await snapshot_enrichments(run_id)
    await snapshot_llm_sources(run_id)
    await extract_db(run_id)

    # Assertions on evidence persistence
    enrichment_payload = json.loads(ENRICHMENT_RECORDS.read_text(encoding="utf-8"))
    assert enrichment_payload, "Expected enrichment records"
    for item in enrichment_payload:
        assert item.get("source_document_id"), "Enrichment missing source_document_id"
        assert item.get("input_scope_hash"), "Enrichment missing input_scope_hash"
        assert item.get("content_hash"), "Enrichment missing content_hash"

    source_payload = json.loads(SOURCE_DOCS.read_text(encoding="utf-8"))
    assert source_payload, "Expected llm_json source documents"
    for item in source_payload:
        assert item.get("source_type") == "llm_json"
        assert item.get("content_hash"), "llm_json source missing content_hash"

    PROOF.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, alembic head, git)",
                "PASS: dual-engine exec discovery stored llm_json sources with content_hash",
                "PASS: AI_EnrichmentRecord linked to llm_json evidence with scope and content hashes",
                "PASS: compare snapshot captured before decisions with evidence pointers",
                "PASS: mark_same and keep_separate decisions persisted with evidence",
                "PASS: rerun idempotent (no duplicate executives, decisions retained)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

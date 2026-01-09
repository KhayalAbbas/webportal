"""Phase 10.12 golden run proof.

End-to-end, deterministic, evidence-first pipeline:
- company discovery via manual-list fixture
- acquisition/fetch + extraction + junk/dedupe
- entity resolution and ranking
- review gate (accept + hold)
- exec discovery gating (fail for unaccepted, succeed for accepted with fixtures)
- export pack + evidence bundle stable hashes

Artifacts written under scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID, uuid4

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT = ARTIFACT_DIR / "phase_10_12_preflight.txt"
PROOF = ARTIFACT_DIR / "phase_10_12_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_12_proof_console.txt"
PIPELINE_SNAPSHOT = ARTIFACT_DIR / "phase_10_12_pipeline_snapshot.json"
EXPORT_HASHES = ARTIFACT_DIR / "phase_10_12_export_hashes.txt"
EXPORT_FILE_LIST = ARTIFACT_DIR / "phase_10_12_export_file_list.txt"
BUNDLE_HASHES = ARTIFACT_DIR / "phase_10_12_bundle_hashes.txt"
BUNDLE_FILE_LIST = ARTIFACT_DIR / "phase_10_12_bundle_file_list.txt"
MANIFEST_EXCERPT = ARTIFACT_DIR / "phase_10_12_manifest_excerpt.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_10_12_db_excerpt.sql.txt"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_10_12_openapi_after.json"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_10_12_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID
ROLE_MANDATE_ID = phase_7_10.ROLE_MANDATE_ID


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"


class DummyUIUser(UIUser):
    def __init__(self, tenant_id: str):
        super().__init__(user_id=uuid4(), tenant_id=UUID(tenant_id), email="ui@example.com", role="admin")


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
        PIPELINE_SNAPSHOT,
        EXPORT_HASHES,
        EXPORT_FILE_LIST,
        BUNDLE_HASHES,
        BUNDLE_FILE_LIST,
        MANIFEST_EXCERPT,
        DB_EXCERPT,
        OPENAPI_AFTER,
        OPENAPI_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_cmd(cmd: List[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def describe_zip(zip_bytes: bytes) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            content = zf.read(info.filename)
            entries.append({
                "name": info.filename,
                "size": len(content),
                "sha256": sha(content),
            })
    return entries


def write_zip_descriptions(zip_bytes: bytes, hashes_file: Path, list_file: Path, label: str) -> None:
    entries = describe_zip(zip_bytes)
    hashes_lines = [f"{label}_sha256 {sha(zip_bytes)} size_bytes {len(zip_bytes)}"]
    list_lines = []
    for entry in entries:
        list_lines.append(f"{entry['name']} size={entry['size']} sha={entry['sha256']}")
    hashes_lines.extend(list_lines)
    hashes_file.write_text("\n".join(hashes_lines) + "\n", encoding="utf-8")
    list_file.write_text("\n".join(list_lines) + "\n", encoding="utf-8")


async def preflight() -> None:
    env = {
        "ATS_API_BASE_URL": os.environ.get("ATS_API_BASE_URL", "http://127.0.0.1:8000"),
        "ATS_ALEMBIC_EXE": os.environ.get("ATS_ALEMBIC_EXE", "alembic"),
        "ATS_GIT_EXE": os.environ.get("ATS_GIT_EXE", "git"),
    }

    lines: list[str] = []

    parsed = requests.utils.urlparse(env["ATS_API_BASE_URL"])
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    port_ok = False
    try:
        with socket.create_connection((host, port), timeout=3):
            port_ok = True
            lines.append(f"PORT_OK host={host} port={port}")
    except OSError as exc:
        lines.append(f"PORT_FAIL host={host} port={port} err={exc}")

    if port_ok:
        health = requests.get(f"{parsed.scheme}://{host}:{port}/health", timeout=10)
        lines.append(f"HEALTH status={health.status_code}")
        openapi_resp = requests.get(f"{parsed.scheme}://{host}:{port}/openapi.json", timeout=15)
        lines.append(f"OPENAPI status={openapi_resp.status_code} length={len(openapi_resp.content)}")
        try:
            data = openapi_resp.json()
            paths = sorted([p for p in data.get("paths", {}) if p.startswith("/company-research/")])
            OPENAPI_EXCERPT.write_text("\n".join(paths) + "\n", encoding="utf-8")
        except Exception:
            OPENAPI_EXCERPT.write_text("<openapi parse failed>\n", encoding="utf-8")
    else:
        lines.append("SKIP_HEALTH_OPENAPI no_listener")

    alembic_exe = env["ATS_ALEMBIC_EXE"]
    heads_rc, heads_out, heads_err = run_cmd([alembic_exe, "heads"])
    current_rc, current_out, current_err = run_cmd([alembic_exe, "current"])
    lines.append(f"ALEMBIC_HEADS rc={heads_rc} {heads_out or heads_err}")
    lines.append(f"ALEMBIC_CURRENT rc={current_rc} {current_out or current_err}")

    git_exe = env["ATS_GIT_EXE"]
    status_rc, status_out, status_err = run_cmd([git_exe, "status", "-sb"])
    log_rc, log_out, log_err = run_cmd([git_exe, "log", "-1", "--decorate"])
    lines.append(f"GIT_STATUS rc={status_rc} {status_out or status_err}")
    lines.append(f"GIT_LOG rc={log_rc} {(log_out.splitlines()[0] if log_out else log_err)}")

    PREFLIGHT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_llm_manual_payload() -> dict:
    return {
        "schema_version": "company_discovery_v1",
        "provider": "proof_fixture",
        "model": "deterministic_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_context": {"query": "phase_10_12_fixture"},
        "companies": [
            {
                "name": "Atlas Proof Holdings",
                "website_url": "https://atlas-proof.example.com",
                "hq_country": "US",
                "hq_city": "New York",
                "sector": "software",
                "subsector": "automation",
                "confidence": 0.91,
                "evidence": [],
            },
            {
                "name": "Beacon Trial Systems",
                "website_url": "https://beacon-trial.example.com",
                "hq_country": "US",
                "hq_city": "Austin",
                "sector": "software",
                "subsector": "data",
                "confidence": 0.87,
                "evidence": [],
            },
        ],
    }


def prospect_summary(prospect: dict) -> str:
    return f"{prospect.get('name_normalized') or prospect.get('name_raw')} ({prospect.get('review_status')}, exec={prospect.get('exec_search_enabled')})"


async def fetch_openapi_after(base_url: str) -> None:
    resp = requests.get(f"{base_url}/openapi.json", timeout=20)
    OPENAPI_AFTER.write_bytes(resp.content)
    try:
        data = resp.json()
        paths = sorted([p for p in data.get("paths", {}) if p.startswith("/company-research/")])
        OPENAPI_EXCERPT.write_text("\n".join(paths) + "\n", encoding="utf-8")
    except Exception:
        OPENAPI_EXCERPT.write_text("<openapi parse failed>\n", encoding="utf-8")


async def write_db_excerpt(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        rows = {}
        tables = {
            "company_research_runs": """
                select id, tenant_id, role_mandate_id, name, status, sector, region_scope, summary, created_at
                from company_research_runs
                where tenant_id = :tenant_id and id = :run_id
            """,
            "company_prospects": """
                select id, name_raw, name_normalized, website_url, review_status, verification_status, exec_search_enabled, discovered_by, created_at
                from company_prospects
                where tenant_id = :tenant_id and company_research_run_id = :run_id
                order by created_at asc
            """,
            "company_prospect_evidence": """
                select company_prospect_id, source_document_id, source_type, source_name, source_url, raw_snippet
                from company_prospect_evidence
                where tenant_id = :tenant_id and company_prospect_id in (select id from company_prospects where tenant_id=:tenant_id and company_research_run_id=:run_id)
                order by company_prospect_id
            """,
            "executive_prospects": """
                select id, company_prospect_id, name_normalized, title, verification_status, review_status, source_document_id, created_at
                from executive_prospects
                where tenant_id = :tenant_id and company_research_run_id = :run_id
                order by created_at asc
            """,
            "executive_prospect_evidence": """
                select executive_prospect_id, source_document_id, source_url, raw_snippet
                from executive_prospect_evidence
                where tenant_id = :tenant_id and executive_prospect_id in (select id from executive_prospects where tenant_id=:tenant_id and company_research_run_id=:run_id)
                order by executive_prospect_id
            """,
            "ai_enrichment_record": """
                select id, target_type, target_id, enrichment_type, provider, purpose, content_hash, source_document_id, company_research_run_id, created_at
                from ai_enrichment_record
                where tenant_id = :tenant_id and company_research_run_id = :run_id
                order by created_at asc
            """,
            "company_research_export_packs": """
                select id, run_id, file_name, storage_pointer, sha256, size_bytes, created_at
                from company_research_export_packs
                where tenant_id = :tenant_id and run_id = :run_id
                order by created_at asc
            """,
        }

        for name, stmt in tables.items():
            result = await session.execute(text(stmt), {"tenant_id": TENANT_ID, "run_id": run_id})
            rows[name] = [dict(r._mapping) for r in result.fetchall()]

    DB_EXCERPT.write_text(json.dumps(rows, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    os.environ["RUN_PROOFS_FIXTURES"] = os.environ.get("RUN_PROOFS_FIXTURES", "1")
    await preflight()

    app.dependency_overrides[verify_user_tenant_access] = lambda: DummyUser(TENANT_ID)
    app.dependency_overrides[get_current_ui_user_and_tenant] = lambda: DummyUIUser(TENANT_ID)

    log("=== Phase 10.12 golden run ===")
    log(f"Tenant: {TENANT_ID}")

    manual_list_text = "\n".join([
        "Atlas Proof Holdings - automation signals",
        "Beacon Trial Systems - data quality tooling",
    ])

    llm_payload = build_llm_manual_payload()

    # Create run via service to avoid FK on created_by_user_id
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        run_obj = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name="Phase 10.12 golden run",
                description="Deterministic end-to-end proof",
                sector="software",
                region_scope=["US"],
                status="active",
            ),
            created_by_user_id=None,
        )
        await session.commit()
        run_id = run_obj.id

    log(f"Run created: {run_id}")

    transport = ASGITransport(app=app)
    base_url = "http://testserver"
    headers = {"X-Tenant-ID": TENANT_ID}

    async with AsyncClient(transport=transport, base_url=base_url) as client:

        # Attach manual list source
        manual_resp = await client.post(
            f"/company-research/runs/{run_id}/sources/list",
            headers=headers,
            json={"title": "golden-manual-list", "content_text": manual_list_text},
        )
        assert manual_resp.status_code == 200, manual_resp.text
        manual_source_id = manual_resp.json()["id"]
        log(f"Manual list source attached: {manual_source_id}")

        # Attach deterministic LLM JSON discovery source
        llm_resp = await client.post(
            f"/company-research/runs/{run_id}/sources/llm-json",
            headers=headers,
            json={"title": "llm discovery", "provider": "proof_fixture", "purpose": "company_discovery", "payload": llm_payload},
        )
        assert llm_resp.status_code == 200, llm_resp.text
        log("LLM discovery payload ingested")

        # Acquire + extract + process
        ae_resp = await client.post(
            f"/company-research/runs/{run_id}/acquire-extract",
            headers=headers,
            json={"force": True, "max_urls": 10},
        )
        assert ae_resp.status_code == 200, ae_resp.text
        ae_summary = ae_resp.json()
        log(f"Acquire+Extract status={ae_summary.get('status')} sources_touched={len(ae_summary.get('source_ids_touched', []))}")

        # Prospect ranking
        rank_resp = await client.get(
            f"/company-research/runs/{run_id}/prospects-ranked",
            headers=headers,
            params={"limit": 10},
        )
        assert rank_resp.status_code == 200, rank_resp.text
        ranked = rank_resp.json()
        assert len(ranked) >= 2, "expected at least two prospects from discovery"
        accept = ranked[0]
        hold = ranked[1]
        log(f"Prospects ranked: accept={prospect_summary(accept)} hold={prospect_summary(hold)}")

        # Review gate
        accept_resp = await client.patch(
            f"/company-research/prospects/{accept['id']}/review-status",
            headers=headers,
            json={"review_status": "accepted", "exec_search_enabled": True},
        )
        assert accept_resp.status_code == 200, accept_resp.text
        hold_resp = await client.patch(
            f"/company-research/prospects/{hold['id']}/review-status",
            headers=headers,
            json={"review_status": "hold", "exec_search_enabled": False},
        )
        assert hold_resp.status_code == 200, hold_resp.text
        log("Review gate applied (accepted + hold)")

        # Exec discovery gate failure for unaccepted company
        bad_payload = {
            "mode": "external",
            "provider": "external_fixture",
            "model": "deterministic",
            "payload": {
                "schema_version": "executive_discovery_v1",
                "provider": "external_fixture",
                "model": "deterministic",
                "generated_at": "2026-01-01T00:00:00Z",
                "query": "phase_10_12_negative",
                "companies": [
                    {"company_name": hold.get("name_normalized"), "company_normalized": hold.get("name_normalized"), "executives": []}
                ],
            },
        }
        fail_resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json=bad_payload,
        )
        assert fail_resp.status_code == 409, fail_resp.text
        fail_body = fail_resp.json()
        # API may wrap error under detail
        fail_error = fail_body.get("error") or fail_body.get("detail", {}).get("error", {})
        assert fail_error.get("code") == "EXEC_DISCOVERY_NOT_ALLOWED", fail_body
        log("Exec discovery gate correctly blocked unaccepted company")

        # Exec discovery success for accepted company using fixtures (dual-engine)
        good_resp = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={
                "mode": "both",
                "engine": "external",
                "provider": "external_fixture",
                "model": "deterministic",
                "title": "golden exec discovery",
                "external_fixture": True,
            },
        )
        assert good_resp.status_code == 200, good_resp.text
        exec_result = good_resp.json()
        log(f"Exec discovery added: internal={exec_result['internal']['execs_added']} external={exec_result['external']['execs_added']}")

        exec_list_resp = await client.get(
            f"/company-research/runs/{run_id}/executives",
            headers=headers,
            params={"company_prospect_id": accept["id"]},
        )
        assert exec_list_resp.status_code == 200, exec_list_resp.text
        executives = exec_list_resp.json()
        assert executives, "expected executives after discovery"

        # Export pack twice for stability
        export_resp1 = await client.get(f"/company-research/runs/{run_id}/export-pack.zip", headers=headers)
        assert export_resp1.status_code == 200, export_resp1.text
        export_bytes1 = export_resp1.content
        export_sha1 = sha(export_bytes1)

        export_resp2 = await client.get(f"/company-research/runs/{run_id}/export-pack.zip", headers=headers)
        assert export_resp2.status_code == 200, export_resp2.text
        export_bytes2 = export_resp2.content
        export_sha2 = sha(export_bytes2)
        assert export_sha1 == export_sha2, "export pack sha changed between runs"
        write_zip_descriptions(export_bytes1, EXPORT_HASHES, EXPORT_FILE_LIST, "export_pack")
        log(f"Export pack stable sha={export_sha1} size={len(export_bytes1)}")

        # Evidence bundle twice for stability
        bundle_resp1 = await client.get(f"/company-research/runs/{run_id}/evidence-bundle", headers=headers)
        assert bundle_resp1.status_code == 200, bundle_resp1.text
        bundle_bytes1 = bundle_resp1.content
        bundle_sha1 = sha(bundle_bytes1)

        bundle_resp2 = await client.get(f"/company-research/runs/{run_id}/evidence-bundle", headers=headers)
        assert bundle_resp2.status_code == 200, bundle_resp2.text
        bundle_bytes2 = bundle_resp2.content
        bundle_sha2 = sha(bundle_bytes2)
        assert bundle_sha1 == bundle_sha2, "evidence bundle sha changed between runs"
        write_zip_descriptions(bundle_bytes1, BUNDLE_HASHES, BUNDLE_FILE_LIST, "evidence_bundle")
        log(f"Evidence bundle stable sha={bundle_sha1} size={len(bundle_bytes1)}")

        # Extract manifest excerpt
        with zipfile.ZipFile(io.BytesIO(bundle_bytes1)) as zf:
            manifest = json.loads(zf.read("MANIFEST.json"))
        write_json(MANIFEST_EXCERPT, manifest)

        snapshot = {
            "run_id": str(run_id),
            "tenant_id": TENANT_ID,
            "sources": {"manual_list_source_id": manual_source_id},
            "acquire_extract": ae_summary,
            "prospects_ranked": ranked,
            "accept_prospect_id": accept["id"],
            "hold_prospect_id": hold["id"],
            "exec_discovery_result": exec_result,
            "executive_count": len(executives),
            "export_pack": {"sha256": export_sha1, "size_bytes": len(export_bytes1)},
            "evidence_bundle": {"sha256": bundle_sha1, "size_bytes": len(bundle_bytes1)},
        }
        write_json(PIPELINE_SNAPSHOT, snapshot)

    await write_db_excerpt(run_id)
    await fetch_openapi_after(os.environ.get("ATS_API_BASE_URL", "http://127.0.0.1:8000"))

    PROOF.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, alembic, git)",
                "PASS: discovery + acquire/extract produced prospects",
                "PASS: review gate enforced (accepted + hold)",
                "PASS: exec discovery gated for unaccepted and succeeded for accepted",
                "PASS: export pack deterministic hash",
                "PASS: evidence bundle deterministic hash and manifest captured",
                "PASS: pipeline snapshot + DB excerpt captured",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

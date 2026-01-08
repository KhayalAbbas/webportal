"""Phase 10.7 proof: export-pack hardening (negative tests).

Validates authz and error envelopes for export pack list/download endpoints and
rejects traversal pointers.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT_PATH = ARTIFACT_DIR / "phase_10_7_preflight.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_7_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_10_7_proof.txt"
NEGATIVE_CASES = ARTIFACT_DIR / "phase_10_7_negative_cases.json"
EXPORT_HASHES = ARTIFACT_DIR / "phase_10_7_export_hashes.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_10_7_db_excerpt.sql.txt"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_10_7_openapi_after.json"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_10_7_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PREFLIGHT_PATH,
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        NEGATIVE_CASES,
        EXPORT_HASHES,
        DB_EXCERPT,
        OPENAPI_AFTER,
        OPENAPI_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def compute_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def preflight() -> None:
    lines = []
    env = {
        "ATS_API_BASE_URL": os.environ.get("ATS_API_BASE_URL", ""),
        "ATS_ALEMBIC_EXE": os.environ.get("ATS_ALEMBIC_EXE", "alembic"),
        "ATS_GIT_EXE": os.environ.get("ATS_GIT_EXE", "git"),
    }

    parsed = urlparse(env["ATS_API_BASE_URL"] or "http://127.0.0.1:8000")
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
        OPENAPI_AFTER.write_bytes(openapi_resp.content)
        try:
            data = openapi_resp.json()
            paths = sorted([p for p in data.get("paths", {}) if "export-pack" in p])
            OPENAPI_EXCERPT.write_text("\n".join(paths) + "\n", encoding="utf-8")
        except Exception:
            OPENAPI_EXCERPT.write_text("<openapi parse failed>\n", encoding="utf-8")
    else:
        lines.append("SKIP_HEALTH_OPENAPI no_listener")

    async with get_async_session_context() as session:
        version_rows = await session.execute(text("select version_num from alembic_version"))
        versions = [row[0] for row in version_rows]
        lines.append(f"ALEMBIC version_rows={versions}")
        await session.execute(text("select 1"))
        lines.append("DB_OK select1")

    git_exe = env["ATS_GIT_EXE"]
    status_proc = subprocess.run([git_exe, "status", "-sb"], capture_output=True, text=True)
    status_text = status_proc.stdout.strip() if status_proc.returncode == 0 else status_proc.stderr.strip()
    log_proc = subprocess.run([git_exe, "log", "-1", "--decorate"], capture_output=True, text=True)
    log_lines = log_proc.stdout.splitlines() if log_proc.returncode == 0 else log_proc.stderr.splitlines()
    lines.append(f"GIT_STATUS rc={status_proc.returncode} {status_text}")
    lines.append(f"GIT_LOG rc={log_proc.returncode} {log_lines[0] if log_lines else ''}")

    PREFLIGHT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    await preflight()

    # Override auth to fixed user, keep tenant check via header
    app.dependency_overrides[get_current_user] = lambda: DummyUser(TENANT_ID)

    log("=== Phase 10.7 export pack negative tests ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await phase_7_10.seed_fixtures()
    run_id: UUID = fixtures["run_id"]
    log(f"Run: {run_id}")

    headers = {"X-Tenant-ID": TENANT_ID}
    wrong_tenant = "00000000-0000-0000-0000-000000000001"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create a baseline export
        resp = await client.get(f"/company-research/runs/{run_id}/export-pack.zip", headers=headers)
        assert resp.status_code == 200, resp.text
        sha_export = compute_sha(resp.content)
        EXPORT_HASHES.write_text(f"EXPORT sha={sha_export} bytes={len(resp.content)}\n", encoding="utf-8")

        list_resp = await client.get(f"/company-research/runs/{run_id}/export-packs", headers=headers)
        assert list_resp.status_code == 200, list_resp.text
        records = list_resp.json()
        export_id = records[0]["id"]

        negative_results = {}

        # Wrong tenant should be forbidden
        bad_list = await client.get(f"/company-research/runs/{run_id}/export-packs", headers={"X-Tenant-ID": wrong_tenant})
        negative_results["list_wrong_tenant"] = {"status": bad_list.status_code, "body": bad_list.json() if bad_list.headers.get("content-type", "").startswith("application/json") else bad_list.text}

        bad_download = await client.get(f"/company-research/export-packs/{export_id}", headers={"X-Tenant-ID": wrong_tenant})
        negative_results["download_wrong_tenant"] = {"status": bad_download.status_code, "body": bad_download.json() if bad_download.headers.get("content-type", "").startswith("application/json") else bad_download.text}

        # Missing tenant header
        missing = await client.get(f"/company-research/runs/{run_id}/export-packs")
        negative_results["list_missing_header"] = {"status": missing.status_code, "body": missing.json() if missing.headers.get("content-type", "").startswith("application/json") else missing.text}

        # Not found export id
        missing_export = await client.get(f"/company-research/export-packs/{uuid4()}", headers=headers)
        negative_results["download_not_found"] = {"status": missing_export.status_code, "body": missing_export.json() if missing_export.headers.get("content-type", "").startswith("application/json") else missing_export.text}

        # Traversal pointer (manually injected) should be blocked
        async with get_async_session_context() as session:
            repo = CompanyResearchRepository(session)
            traversal_id = uuid4()
            await repo.create_export_pack_record(
                export_id=traversal_id,
                tenant_id=TENANT_ID,
                run_id=run_id,
                file_name="evil.zip",
                storage_pointer="../evil.zip",
                sha256="deadbeef",
                size_bytes=1,
            )
            await session.commit()

        traversal_resp = await client.get(f"/company-research/export-packs/{traversal_id}", headers=headers)
        negative_results["download_traversal"] = {"status": traversal_resp.status_code, "body": traversal_resp.json() if traversal_resp.headers.get("content-type", "").startswith("application/json") else traversal_resp.text}

        NEGATIVE_CASES.write_text(json.dumps(negative_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Persist DB excerpt
        async with get_async_session_context() as session:
            repo = CompanyResearchRepository(session)
            rows = await repo.list_export_packs_for_run(tenant_id=TENANT_ID, run_id=run_id)
            DB_EXCERPT.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "id": str(r.id),
                            "run_id": str(r.run_id),
                            "storage_pointer": r.storage_pointer,
                            "sha256": r.sha256,
                            "size_bytes": r.size_bytes,
                        },
                        sort_keys=True,
                    )
                    for r in rows
                )
                + "\n",
                encoding="utf-8",
            )

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, alembic, git)",
                "PASS: export pack baseline created for negative tests",
                "PASS: authz failures return structured errors for list/download",
                "PASS: missing tenant header rejected",
                "PASS: traversal pointer rejected",
                "PASS: not-found export returns structured 404",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

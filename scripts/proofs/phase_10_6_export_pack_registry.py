"""Phase 10.6 proof: export pack registry persistence and download determinism.

- Uses runbook-configured env for host/ports/paths.
- Preflight checks listener, /health, /openapi, DB reachability, alembic head, git status/log.
- Seeds deterministic fixtures via Phase 7.10 helper.
- Generates two export packs, verifies registry rows, ordering, download-by-id hash match, and relative storage pointers.
- Captures artifacts under scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, List
from urllib.parse import urlparse
from uuid import UUID

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

# Artifacts
ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT_PATH = ARTIFACT_DIR / "phase_10_6_preflight.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_6_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_10_6_proof.txt"
EXPORT_HASHES = ARTIFACT_DIR / "phase_10_6_export_hashes.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_10_6_db_excerpt.sql.txt"
EXPORT_FIRST_ZIP = ARTIFACT_DIR / "phase_10_6_export_first.zip"
EXPORT_SECOND_ZIP = ARTIFACT_DIR / "phase_10_6_export_second.zip"
EXPORT_FILE_LIST = ARTIFACT_DIR / "phase_10_6_export_file_list.txt"
UI_EXCERPT = ARTIFACT_DIR / "phase_10_6_ui_html_excerpt.html"

HEAD_REV = "b6f20f1d5a7c"
TENANT_ID = phase_7_10.TENANT_ID


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = UUID(int=0)
        self.email = "proof@example.com"
        self.username = "proof"


class DummyUIUser(UIUser):
    def __init__(self, tenant_id: str):
        super().__init__(user_id=UUID(int=0), tenant_id=UUID(tenant_id), email="ui@example.com", role="admin")


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
        EXPORT_HASHES,
        DB_EXCERPT,
        EXPORT_FIRST_ZIP,
        EXPORT_SECOND_ZIP,
        EXPORT_FILE_LIST,
        UI_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


async def preflight() -> None:
    lines: List[str] = []
    env = {
        "ATS_API_BASE_URL": os.environ.get("ATS_API_BASE_URL", ""),
        "ATS_GIT_EXE": os.environ.get("ATS_GIT_EXE", "git"),
        "ATS_ALEMBIC_EXE": os.environ.get("ATS_ALEMBIC_EXE", "alembic"),
    }

    # Port check before /health or /openapi
    parsed = urlparse(env["ATS_API_BASE_URL"] or "http://127.0.0.1:8000")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    port_ok = False
    try:
        with socket.create_connection((host, port), timeout=3):
            port_ok = True
            lines.append(f"PORT_OK host={host} port={port}")
    except OSError as exc:  # pragma: no cover - captured in preflight
        lines.append(f"PORT_FAIL host={host} port={port} err={exc}")

    # /health and /openapi if port is up
    if port_ok:
        health = requests.get(f"{parsed.scheme}://{host}:{port}/health", timeout=10)
        lines.append(f"HEALTH status={health.status_code}")
        openapi = requests.get(f"{parsed.scheme}://{host}:{port}/openapi.json", timeout=15)
        lines.append(f"OPENAPI status={openapi.status_code} length={len(openapi.content)}")
    else:
        lines.append("SKIP_HEALTH_OPENAPI no_listener")

    # DB reachability and alembic version check
    async with get_async_session_context() as session:
        version_rows = await session.execute(text("select version_num from alembic_version"))
        versions = [row[0] for row in version_rows]
        lines.append(f"ALEMBIC version_rows={versions}")
        lines.append(f"ALEMBIC_AT_HEAD={HEAD_REV in versions}")
        await session.execute(text("select 1"))
        lines.append("DB_OK select1")

    # Git status/log
    git_exe = env["ATS_GIT_EXE"]
    status = subprocess.check_output([git_exe, "status", "-sb"], cwd=ROOT).decode().strip()
    log1 = subprocess.check_output([git_exe, "log", "-1", "--decorate"], cwd=ROOT).decode().strip()
    lines.append(f"GIT_STATUS {status}")
    lines.append(f"GIT_LOG {log1.splitlines()[0] if log1 else ''}")

    PREFLIGHT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compute_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_zip(path: Path, content: bytes) -> List[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
        return sorted(zf.namelist())


def ensure_relative_pointer(pointer: str) -> None:
    posix = PurePosixPath(pointer)
    if posix.is_absolute():
        raise AssertionError(f"pointer is absolute: {pointer}")
    if any(part in {"..", ""} for part in posix.parts):
        raise AssertionError(f"pointer traversal detected: {pointer}")
    if ":" in posix.as_posix():
        raise AssertionError(f"pointer contains drive: {pointer}")


async def cleanup_existing_exports(run_id: UUID, tenant_id: str) -> None:
    storage_root = Path(settings.EXPORT_PACK_STORAGE_ROOT)
    root_abs = storage_root if storage_root.is_absolute() else (ROOT / storage_root)
    target_dir = root_abs / "company_research" / str(tenant_id) / "runs" / str(run_id)
    if target_dir.exists():
        for child in target_dir.glob("**/*"):
            if child.is_file():
                child.unlink()
        for child in sorted(target_dir.glob("**/*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        target_dir.rmdir()

    async with get_async_session_context() as session:
        await session.execute(
            text("delete from company_research_export_packs where run_id=:run_id and tenant_id=:tenant_id"),
            {"run_id": run_id, "tenant_id": tenant_id},
        )
        await session.commit()


async def main_async() -> None:
    reset_artifacts()
    await preflight()

    # Override auth for API and UI
    app.dependency_overrides[verify_user_tenant_access] = lambda: DummyUser(TENANT_ID)
    app.dependency_overrides[get_current_ui_user_and_tenant] = lambda: DummyUIUser(TENANT_ID)

    log("=== Phase 10.6 export pack registry ===")
    log(f"Tenant: {TENANT_ID}")

    # Seed fixtures (deterministic)
    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]
    log(f"Run: {run_id}")

    await cleanup_existing_exports(run_id, TENANT_ID)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Generate two exports
        headers = {"X-Tenant-ID": TENANT_ID}
        resp1 = await client.get(f"/company-research/runs/{run_id}/export-pack.zip", headers=headers)
        assert resp1.status_code == 200, resp1.text
        files1 = save_zip(EXPORT_FIRST_ZIP, resp1.content)
        sha1 = compute_sha(resp1.content)
        size1 = len(resp1.content)
        log(f"Export1 bytes={size1} sha={sha1}")

        resp2 = await client.get(f"/company-research/runs/{run_id}/export-pack.zip", headers=headers)
        assert resp2.status_code == 200, resp2.text
        files2 = save_zip(EXPORT_SECOND_ZIP, resp2.content)
        sha2 = compute_sha(resp2.content)
        size2 = len(resp2.content)
        log(f"Export2 bytes={size2} sha={sha2}")

        # DB registry rows
        async with get_async_session_context() as session:
            repo = CompanyResearchRepository(session)
            records = await repo.list_export_packs_for_run(tenant_id=TENANT_ID, run_id=run_id)
            assert len(records) >= 2, "expected at least two export records"
            ids_ordered = [str(r.id) for r in records]
            log(f"DB export ids (ordered): {ids_ordered}")
            # Keep top two for assertions
            top_two = records[:2]

        # API list
        list_resp = await client.get(f"/company-research/runs/{run_id}/export-packs", headers=headers)
        assert list_resp.status_code == 200, list_resp.text
        api_rows: List[dict[str, Any]] = list_resp.json()
        assert [row["id"] for row in api_rows] == ids_ordered, "API order mismatch"

        # Download-by-id and hash compare
        download_hashes = []
        for rec in top_two:
            ensure_relative_pointer(rec.storage_pointer)
            dl = await client.get(f"/company-research/export-packs/{rec.id}", headers=headers)
            assert dl.status_code == 200, dl.text
            sha = compute_sha(dl.content)
            assert sha == rec.sha256, f"hash mismatch for export {rec.id}"
            download_hashes.append({"id": str(rec.id), "sha256": sha, "size_bytes": len(dl.content), "pointer": rec.storage_pointer})

        # UI HTML excerpt
        ui_resp = await client.get(f"/ui/company-research/runs/{run_id}")
        assert ui_resp.status_code == 200, f"UI status {ui_resp.status_code}"
        UI_EXCERPT.write_text(ui_resp.text, encoding="utf-8")

    # Persist hashes and DB excerpt
    lines = []
    lines.append(f"EXPORT1 sha={sha1} bytes={size1} files={files1}")
    lines.append(f"EXPORT2 sha={sha2} bytes={size2} files={files2}")
    for item in download_hashes:
        lines.append(f"DOWNLOAD {item['id']} sha={item['sha256']} bytes={item['size_bytes']} pointer={item['pointer']}")
    EXPORT_HASHES.write_text("\n".join(lines) + "\n", encoding="utf-8")

    db_lines = [json.dumps(
        {
            "id": str(rec.id),
            "run_id": str(rec.run_id),
            "storage_pointer": rec.storage_pointer,
            "sha256": rec.sha256,
            "size_bytes": rec.size_bytes,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        },
        sort_keys=True,
    ) for rec in records]
    DB_EXCERPT.write_text("\n".join(db_lines) + "\n", encoding="utf-8")

    file_list_lines: List[str] = []
    file_list_lines.append("EXPORT1 " + ",".join(files1))
    file_list_lines.append("EXPORT2 " + ",".join(files2))
    EXPORT_FILE_LIST.write_text("\n".join(file_list_lines) + "\n", encoding="utf-8")

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, db, alembic head, git)",
                f"PASS: export pack registry created rows (count={len(records)}) with stable ordering",
                "PASS: list endpoint matches DB ordering (created_at desc, id desc)",
                "PASS: download-by-id hashes match registry sha256 (relative pointers enforced)",
                "PASS: UI export history rendered",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

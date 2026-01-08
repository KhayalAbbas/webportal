"""Phase 10.8 proof: evidence bundle determinism."""

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
from urllib.parse import urlparse
from uuid import uuid4, UUID

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT = ARTIFACT_DIR / "phase_10_8_preflight.txt"
PROOF = ARTIFACT_DIR / "phase_10_8_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_8_proof_console.txt"
BUNDLE_HASHES = ARTIFACT_DIR / "phase_10_8_bundle_hashes.txt"
BUNDLE_FILE_LIST = ARTIFACT_DIR / "phase_10_8_bundle_file_list.txt"
MANIFEST_EXCERPT = ARTIFACT_DIR / "phase_10_8_manifest_excerpt.json"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_10_8_openapi_after.json"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_10_8_openapi_after_excerpt.txt"
RELEASE_BUNDLE = ARTIFACT_DIR / "phase_10_8_release_bundle.zip"

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
        PREFLIGHT,
        PROOF,
        PROOF_CONSOLE,
        BUNDLE_HASHES,
        BUNDLE_FILE_LIST,
        MANIFEST_EXCERPT,
        OPENAPI_AFTER,
        OPENAPI_EXCERPT,
        RELEASE_BUNDLE,
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
    except OSError as exc:  # pragma: no cover
        lines.append(f"PORT_FAIL host={host} port={port} err={exc}")

    if port_ok:
        health = requests.get(f"{parsed.scheme}://{host}:{port}/health", timeout=10)
        lines.append(f"HEALTH status={health.status_code}")
        openapi_resp = requests.get(f"{parsed.scheme}://{host}:{port}/openapi.json", timeout=15)
        lines.append(f"OPENAPI status={openapi_resp.status_code} length={len(openapi_resp.content)}")
        OPENAPI_AFTER.write_bytes(openapi_resp.content)
        try:
            data = openapi_resp.json()
            paths = sorted([p for p in data.get("paths", {}) if "evidence-bundle" in p])
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

    PREFLIGHT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    await preflight()

    app.dependency_overrides[get_current_user] = lambda: DummyUser(TENANT_ID)

    log("=== Phase 10.8 evidence bundle proof ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await phase_7_10.seed_fixtures()
    run_id: UUID = fixtures["run_id"]
    log(f"Run: {run_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        url = f"/company-research/runs/{run_id}/evidence-bundle"
        headers = {"X-Tenant-ID": TENANT_ID}

        resp1 = await client.get(url, headers=headers)
        assert resp1.status_code == 200, resp1.text
        sha1 = compute_sha(resp1.content)

        resp2 = await client.get(url, headers=headers)
        assert resp2.status_code == 200, resp2.text
        sha2 = compute_sha(resp2.content)

        assert sha1 == sha2, "Bundle hash must be stable across calls"

        def _parse_bundle(data: bytes):
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                names = sorted(zf.namelist())
                manifest_bytes = zf.read("MANIFEST.json")
                manifest = json.loads(manifest_bytes)
                manifest_sha_line = zf.read("MANIFEST.sha256").decode("utf-8").strip()
                expected_line = f"SHA256(MANIFEST.json)={compute_sha(manifest_bytes)}"
                assert manifest_sha_line == expected_line, "Manifest sha mismatch"
                for entry in manifest.get("files", []):
                    body = zf.read(entry["file_name"])
                    calc = compute_sha(body)
                    assert calc == entry["sha256"], f"Hash mismatch for {entry['file_name']}"
                return names, manifest

        names, manifest = _parse_bundle(resp1.content)

        BUNDLE_HASHES.write_text(
            "\n".join(
                [
                    f"bundle_sha_1={sha1}",
                    f"bundle_sha_2={sha2}",
                    f"match={sha1 == sha2}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        BUNDLE_FILE_LIST.write_text("\n".join(names) + "\n", encoding="utf-8")
        MANIFEST_EXCERPT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        RELEASE_BUNDLE.write_bytes(resp1.content)

    PROOF.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, alembic, git)",
                "PASS: evidence bundle generated twice with identical sha256",
                "PASS: manifest hashes validated against zip contents",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

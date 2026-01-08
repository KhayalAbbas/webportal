"""Phase 10.5 Silver Arrow UI proof.

Runbook-aware, auto-start capable preflight plus UI front-door export validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.jwt import create_access_token  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.company_research import CompanyResearchRun  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.ui.session import session_manager  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import FixtureHandler, find_free_server  # noqa: E402

ARTIFACTS_DIR = Path("scripts/proofs/_artifacts")
PREFLIGHT_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_preflight.txt"
RUNBOOK_EXCERPT_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_runbook_excerpt.txt"
OPENAPI_BEFORE_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_openapi_before.json"
API_START_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_api_start_console.txt"
EXPORT_HASH_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_export_hashes.txt"
RUN_DETAIL_HTML_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_run_detail.html"
PROOF_ARTIFACT = ARTIFACTS_DIR / "phase_10_5_proof.txt"
TENANT_FIXED_ID = UUID("8b5c5d3e-8c4c-4c9d-8db7-5f6d8d7c0a11")
RUNBOOK_PATH = Path("scripts/runbook/LOCAL_COMMANDS.ps1")


class RunbookError(RuntimeError):
    pass


def _fail(msg: str) -> None:
    raise RunbookError(msg)


def _write_artifact(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_runbook_vars(path: Path) -> Dict[str, str]:
    if not path.exists():
        _fail("Runbook missing: scripts/runbook/LOCAL_COMMANDS.ps1")

    content = path.read_text(encoding="utf-8")
    keys = [
        "ATS_API_BASE_URL",
        "ATS_PYTHON_EXE",
        "ATS_ALEMBIC_EXE",
        "ATS_GIT_EXE",
        "ATS_START_API_CMD",
    ]
    values: Dict[str, str] = {}
    for key in keys:
        env_val = os.getenv(key)
        if env_val:
            values[key] = env_val
            continue
        pattern = rf"\${key}\s*=\s*['\"]([^'\"]+)['\"]"
        match = re.search(pattern, content)
        if match:
            values[key] = match.group(1)
    missing = [k for k in keys if k not in values]
    if missing:
        _fail(f"Runbook variables missing: {', '.join(missing)}. Update LOCAL_COMMANDS.ps1 or set env vars.")
    return values


def _redact(value: str) -> str:
    lowered = value.lower()
    if any(token in lowered for token in ["secret", "token", "key", "pwd", "pass"]):
        return "<redacted>"
    return value


def _port_is_listening(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


async def _stream_process_output(proc: asyncio.subprocess.Process, buffer: list[str]) -> None:
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace")
        buffer.append(line)
        _write_artifact(API_START_ARTIFACT, "".join(buffer))


async def _start_api_if_needed(base_url: str, cmd: str) -> Tuple[Optional[asyncio.subprocess.Process], Optional[asyncio.Task], list[str]]:
    if _port_is_listening(base_url):
        return None, None, []

    if os.getenv("ALLOW_START_API") != "1":
        _fail(f"API port not listening. Start the API using: {cmd}")

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    buffer: list[str] = [f"started: {cmd}\n"]
    _write_artifact(API_START_ARTIFACT, "".join(buffer))
    task = asyncio.create_task(_stream_process_output(proc, buffer))
    return proc, task, buffer


async def _wait_for_health(base_url: str, timeout_seconds: float = 45.0) -> Tuple[httpx.Response, httpx.Response]:
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        last_health: Optional[httpx.Response] = None
        last_openapi: Optional[httpx.Response] = None
        while True:
            try:
                last_health = await client.get("/health")
                if last_health.status_code == 200:
                    last_openapi = await client.get("/openapi.json")
                    if last_openapi.status_code == 200:
                        return last_health, last_openapi
            except httpx.HTTPError:
                pass
            if time.monotonic() - started > timeout_seconds:
                break
            await asyncio.sleep(1.0)
    raise RunbookError("API health/openapi did not become ready in time")


@contextmanager
def _fixture_server():
    server = find_free_server("127.0.0.1")
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=5)


async def _ensure_tenant_and_role() -> Tuple[UUID, UUID, str]:
    tenant_status = "existing"
    async with AsyncSessionLocal() as session:
        tenant_row = await session.execute(select(Tenant).where(Tenant.id == TENANT_FIXED_ID).limit(1))
        tenant = tenant_row.scalar_one_or_none()
        if not tenant:
            tenant_status = "created"
            tenant = Tenant(id=TENANT_FIXED_ID, name="Proof Tenant", status="active")
            session.add(tenant)
            await session.flush()

        company_row = await session.execute(
            select(Company).where(Company.tenant_id == tenant.id).order_by(Company.created_at).limit(1)
        )
        company = company_row.scalar_one_or_none()
        if not company:
            company = Company(
                tenant_id=tenant.id,
                name="Proof Company",
                industry="testing",
                headquarters_location="Remote",
                website="https://example.com",
                notes="auto-created for phase 10.5 proof",
            )
            session.add(company)
            await session.flush()

        role_row = await session.execute(
            select(Role).where(Role.tenant_id == tenant.id).order_by(Role.created_at).limit(1)
        )
        role = role_row.scalar_one_or_none()
        if not role:
            role = Role(
                tenant_id=tenant.id,
                company_id=company.id,
                title="Proof Role",
                function="testing",
                status="open",
                description="auto-created for phase 10.5 proof",
            )
            session.add(role)
            await session.flush()

        await session.commit()
        return UUID(str(tenant.id)), UUID(str(role.id)), tenant_status


async def _ensure_user(tenant_id: UUID) -> Tuple[UUID, str, str]:
    email = "proof-ui@example.com"
    password = "ProofPass123!"

    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(tenant_id, email)
        if not user:
            user = await repo.create(
                UserCreate(
                    tenant_id=tenant_id,
                    email=email,
                    full_name="Proof UI",
                    password=password,
                    role="admin",
                )
            )
            await session.commit()
        else:
            await session.commit()

        bearer = create_access_token(
            {
                "user_id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "email": user.email,
                "role": user.role,
            }
        )
        session_cookie = session_manager.create_session_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
        )
        return UUID(str(user.id)), bearer, session_cookie


async def _ensure_run(tenant_id: UUID, role_id: UUID) -> UUID:
    run_name = "phase_10_5_ui_front_door"
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(CompanyResearchRun.id)
                .where(CompanyResearchRun.tenant_id == tenant_id)
                .where(CompanyResearchRun.name == run_name)
                .limit(1)
        )
        row = existing.scalar_one_or_none()
        if row:
            return UUID(str(row))

        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=str(tenant_id),
            data=CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name=run_name,
                description="Phase 10.5 UI proof run",
                sector="testing",
                region_scope=["US"],
                status="active",
            ),
            created_by_user_id=None,
        )
        await session.commit()
        return UUID(str(run.id))


async def _download_and_hash(client: httpx.AsyncClient, url: str) -> Tuple[str, int]:
    resp = await client.get(url)
    resp.raise_for_status()
    digest = hashlib.sha256(resp.content).hexdigest()
    return digest, len(resp.content)


async def run_proof() -> None:
    rb = _parse_runbook_vars(RUNBOOK_PATH)
    redacted = {k: _redact(v) for k, v in rb.items()}
    _write_artifact(RUNBOOK_EXCERPT_ARTIFACT, json.dumps(redacted, indent=2))

    base_url = rb["ATS_API_BASE_URL"].rstrip("/")
    proc, task, _ = await _start_api_if_needed(base_url, rb["ATS_START_API_CMD"])

    try:
        health, openapi_resp = await _wait_for_health(base_url)
        _write_artifact(OPENAPI_BEFORE_ARTIFACT, json.dumps(openapi_resp.json(), indent=2))

        preflight_lines = [
            f"api_base_url={base_url}",
            f"health_status={health.status_code}",
            f"openapi_status={openapi_resp.status_code}",
            f"openapi_content_length={len(openapi_resp.content)}",
        ]
        _write_artifact(PREFLIGHT_ARTIFACT, "\n".join(preflight_lines) + "\n")

        tenant_id, role_id, tenant_status = await _ensure_tenant_and_role()
        user_id, bearer, session_cookie = await _ensure_user(tenant_id)
        run_id = await _ensure_run(tenant_id, role_id)

        headers = {
            "Authorization": f"Bearer {bearer}",
            "X-Tenant-ID": str(tenant_id),
        }

        hash1 = hash2 = ""
        size1 = size2 = 0

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0) as api_client:
            # Optional: ensure run still exists
            await api_client.get(f"/company-research/runs/{run_id}")

            # Download export pack twice for stability
            export_url = f"/company-research/runs/{run_id}/export-pack.zip"
            hash1, size1 = await _download_and_hash(api_client, export_url)
            hash2, size2 = await _download_and_hash(api_client, export_url)
            lines = [
                f"export_url={export_url}",
                f"hash1={hash1}",
                f"hash2={hash2}",
                f"size1={size1}",
                f"size2={size2}",
                f"hashes_match={hash1 == hash2}",
            ]
            _write_artifact(EXPORT_HASH_ARTIFACT, "\n".join(lines) + "\n")

        async with httpx.AsyncClient(
            base_url=base_url,
            cookies={"session": session_cookie},
            timeout=30.0,
        ) as ui_client:
            resp = await ui_client.get(f"/ui/company-research/runs/{run_id}")
            resp.raise_for_status()
            _write_artifact(RUN_DETAIL_HTML_ARTIFACT, resp.text)

        proof_lines = [
            "ASSERT: /health returns 200",
            "ASSERT: /openapi.json returns 200",
            "ASSERT: export-pack.zip SHA256 stable across two pulls",
            f"tenant_id={tenant_id} ({tenant_status})",
            f"health_status={health.status_code}",
            f"openapi_status={openapi_resp.status_code}",
            f"export_url=/company-research/runs/{run_id}/export-pack.zip",
            f"hash1={hash1}",
            f"hash2={hash2}",
            f"size1={size1}",
            f"size2={size2}",
            f"hashes_match={hash1 == hash2}",
            "RESULT=PASS",
        ]
        _write_artifact(PROOF_ARTIFACT, "\n".join(proof_lines) + "\n")
    finally:
        if proc and os.getenv("KEEP_API_RUNNING") != "1":
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
            if task:
                task.cancel()


def main() -> None:
    try:
        asyncio.run(run_proof())
    except RunbookError as exc:
        _write_artifact(PREFLIGHT_ARTIFACT, f"FAIL: {exc}\n")
        raise


if __name__ == "__main__":
    main()

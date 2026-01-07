"""Phase 9.2 preflight: health, openapi, alembic head check, git snapshot."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402

ARTIFACT = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_9_2_preflight.txt"
OPENAPI_BEFORE = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_9_2_openapi_before.json"
GIT = r"C:\\Program Files\\Git\\cmd\\git.exe"


def snapshot_git() -> str:
    status = subprocess.check_output([GIT, "status", "-sb"], cwd=ROOT).decode()
    log = subprocess.check_output([GIT, "log", "-1", "--decorate"], cwd=ROOT).decode()
    return f"git status -sb\n{status}\n.git log -1 --decorate\n{log}"


async def snapshot_http() -> tuple[str, int]:
    async with httpx.AsyncClient(app=app, base_url="http://testserver") as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200, f"unexpected health status {health_resp.status_code}"
        health_line = f"health status={health_resp.status_code} body={health_resp.json()}"

        openapi_resp = await client.get("/openapi.json")
        assert openapi_resp.status_code == 200, f"unexpected openapi status {openapi_resp.status_code}"
        payload = openapi_resp.json()
        OPENAPI_BEFORE.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        content = json.dumps(payload, sort_keys=True)
        openapi_len = len(content.encode("utf-8"))

    return health_line, openapi_len


async def snapshot_db() -> str:
    async with get_async_session_context() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
    return f"db ping: {value}"


async def snapshot_alembic() -> str:
    cfg = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    heads = ",".join(sorted(script.get_heads()))

    async with get_async_session_context() as session:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        current = str(result.scalar())

    return f"alembic current={current} head={head} heads={heads}"


async def main_async() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)

    health_line, openapi_len = await snapshot_http()
    db_line = await snapshot_db()
    alembic_line = await snapshot_alembic()
    git_blob = snapshot_git()

    lines = [
        health_line,
        f"openapi status=200 length={openapi_len}",
        db_line,
        alembic_line,
        git_blob,
    ]

    ARTIFACT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(ARTIFACT)


if __name__ == "__main__":
    asyncio.run(main_async())

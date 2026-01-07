"""Phase 8.3 preflight: openapi, db ping, alembic head check, git snapshot."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.db.session import get_async_session_context
from app.main import app


ARTIFACT = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_8_3_preflight.txt"
GIT = "C:/Program Files/Git/bin/git.exe"


def snapshot_git() -> str:
    status = subprocess.check_output([GIT, "status", "-sb"], cwd=ROOT).decode()
    log = subprocess.check_output([GIT, "log", "-1", "--decorate"], cwd=ROOT).decode()
    return f"git status -sb\n{status}\n.git log -1 --decorate\n{log}"


def snapshot_openapi() -> tuple[int, int]:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200, f"unexpected openapi status {response.status_code}"
    payload = response.json()
    content = json.dumps(payload, sort_keys=True)
    return response.status_code, len(content.encode("utf-8"))


async def snapshot_db() -> str:
    async with get_async_session_context() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
    return f"db ping: {value}"


def snapshot_alembic() -> str:
    cfg = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    async def _get_current_version() -> str:
        async with get_async_session_context() as session:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            return str(result.scalar())

    current = asyncio.get_event_loop().run_until_complete(_get_current_version())
    return f"alembic current={current} head={head}"


def main() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)

    status_code, openapi_len = snapshot_openapi()
    db_line = asyncio.get_event_loop().run_until_complete(snapshot_db())
    alembic_line = snapshot_alembic()
    git_blob = snapshot_git()

    lines = [
        f"openapi status={status_code} length={openapi_len}",
        db_line,
        alembic_line,
        git_blob,
    ]

    ARTIFACT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(ARTIFACT)


if __name__ == "__main__":
    main()
import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

GIT_EXE = Path("C:/Program Files/Git/bin/git.exe")
ALEMBIC_EXE = ROOT / ".venv" / "Scripts" / "alembic.exe"
ARTIFACT = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_7_12_preflight.txt"
ARTIFACT.parent.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = result.stdout.strip()
    err = result.stderr.strip()
    combined = "\n".join([part for part in (out, err) if part])
    return combined or "<no output>"


sections: list[str] = []

sections.append("== git status -sb ==")
sections.append(run_cmd([str(GIT_EXE), "status", "-sb"]))

sections.append("\n== git log -1 --decorate ==")
sections.append(run_cmd([str(GIT_EXE), "log", "-1", "--decorate"]))

sections.append("\n== git tag --points-at HEAD ==")
sections.append(run_cmd([str(GIT_EXE), "tag", "--points-at", "HEAD"]))

sections.append("\n== alembic current ==")
sections.append(run_cmd([str(ALEMBIC_EXE), "current"]))

sections.append("\n== alembic heads ==")
sections.append(run_cmd([str(ALEMBIC_EXE), "heads"]))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
resp = client.get("/openapi.json")
sections.append(f"\n== GET /openapi.json status {resp.status_code} length {len(resp.text)} ==")
openapi_lines = resp.text.splitlines()[:60]
sections.extend(openapi_lines or ["<no openapi content>"])

from sqlalchemy import text as sql_text
from app.db.session import get_async_session_context


async def db_connectivity() -> None:
    async with get_async_session_context() as session:
        result = await session.execute(sql_text("SELECT 1 as ok"))
        val = result.scalar()
        sections.append("\n== db connectivity check ==")
        sections.append(f"db_ok=true value={val}")


asyncio.run(db_connectivity())

ARTIFACT.write_text("\n".join(sections) + "\n", encoding="utf-8")
print(f"wrote {ARTIFACT.relative_to(ROOT)}")

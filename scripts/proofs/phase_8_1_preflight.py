import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import text as sql_text

from app.db.session import get_async_session_context
from app.main import app

GIT_EXE = Path("C:/Program Files/Git/bin/git.exe")
ALEMBIC_EXE = ROOT / ".venv" / "Scripts" / "alembic.exe"
ARTIFACT = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_8_1_preflight.txt"
ARTIFACT.parent.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = result.stdout.strip()
    err = result.stderr.strip()
    combined = "\n".join([part for part in (out, err) if part])
    return combined or "<no output>"


def capture_openapi() -> str:
    client = TestClient(app)
    resp = client.get("/openapi.json")
    length = len(resp.text or "")
    return f"status={resp.status_code} length={length}"


async def db_connectivity(sections: list[str]) -> None:
    async with get_async_session_context() as session:
        result = await session.execute(sql_text("SELECT 1 as ok"))
        val = result.scalar()
        sections.append("== db connectivity ==")
        sections.append(f"db_ok=true value={val}")


def main() -> None:
    sections: list[str] = []

    sections.append("== git status -sb ==")
    sections.append(run_cmd([str(GIT_EXE), "status", "-sb"]))

    sections.append("\n== git log -1 --decorate ==")
    sections.append(run_cmd([str(GIT_EXE), "log", "-1", "--decorate"]))

    sections.append("\n== alembic current ==")
    sections.append(run_cmd([str(ALEMBIC_EXE), "current"]))

    sections.append("\n== alembic heads ==")
    sections.append(run_cmd([str(ALEMBIC_EXE), "heads"]))

    sections.append("\n== openapi status/length ==")
    sections.append(capture_openapi())

    asyncio.run(db_connectivity(sections))

    ARTIFACT.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from httpx import AsyncClient, ASGITransport

from app.main import app

ARTIFACT = Path("scripts/proofs/_artifacts/phase_9_7_verify_close_preflight.txt")
OPENAPI = Path("scripts/proofs/_artifacts/phase_9_7_verify_close_openapi.json")


def run_cmd(label: str, cmd: list[str], lines: list[str], env: dict[str, str]) -> None:
    binary = cmd[0]
    resolved = shutil.which(binary)
    if not resolved:
        if binary.lower() == "git":
            fallback = Path("C:/Program Files/Git/bin/git.exe")
            resolved = str(fallback)
        elif binary.lower() == "alembic":
            resolved = str(Path("C:/ATS/.venv/Scripts/alembic.exe"))
        else:
            resolved = binary
    proc = subprocess.run([resolved, *cmd[1:]], capture_output=True, text=True, env=env)
    lines.append(f"## {label}")
    lines.append(proc.stdout.strip() or "<no stdout>")
    if proc.stderr.strip():
        lines.append("-- stderr --")
        lines.append(proc.stderr.strip())


async def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    lines: list[str] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        openapi = await client.get("/openapi.json")

    OPENAPI.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI.write_text(json.dumps(openapi.json(), indent=2), encoding="utf-8")

    lines.append(f"GET /health status={health.status_code} body={health.text.strip()}")
    lines.append(f"GET /openapi.json status={openapi.status_code} length={len(openapi.text)}")

    run_cmd("alembic current", ["alembic", "current"], lines, env)
    run_cmd("alembic heads", ["alembic", "heads"], lines, env)
    run_cmd("git status -sb", ["git", "status", "-sb"], lines, env)
    run_cmd("git log -1 --decorate", ["git", "log", "-1", "--decorate"], lines, env)

    ARTIFACT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

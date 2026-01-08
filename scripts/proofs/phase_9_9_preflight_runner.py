import asyncio
import json
import os
import shutil
import string
import subprocess
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import app

ART_DIR = Path("scripts/proofs/_artifacts")
PRE_FLIGHT = ART_DIR / "phase_9_9_preflight.txt"
OPENAPI_BEFORE = ART_DIR / "phase_9_9_openapi_before.json"


def run_cmd(cmd: list[str]) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    binary = cmd[0]
    resolved = shutil.which(binary)
    if not resolved:
        if binary.lower() == "git":
            resolved = "C:/Program Files/Git/cmd/git.exe"
        elif binary.lower() == "alembic":
            resolved = "C:/ATS/.venv/Scripts/alembic.exe"
        else:
            resolved = binary

    res = subprocess.run([resolved, *cmd[1:]], capture_output=True, text=True, env=env)
    out = res.stdout + res.stderr
    if res.returncode != 0:
        raise SystemExit(f"Command failed {[resolved, *cmd[1:]]}: {res.returncode}\n{out}")
    return out.strip()


def extract_revisions(output: str) -> set[str]:
    revs: set[str] = set()
    for line in output.splitlines():
        for token in line.split():
            if len(token) == 12 and all(ch in string.hexdigits for ch in token):
                revs.add(token)
    return revs


def ensure_at_head(current_out: str, heads_out: str) -> None:
    current_revs = extract_revisions(current_out)
    head_revs = extract_revisions(heads_out)
    if not current_revs or not head_revs or not current_revs.issubset(head_revs):
        raise SystemExit(
            "Alembic not at head:\n"
            f"current: {sorted(current_revs)}\n"
            f"heads: {sorted(head_revs)}"
        )


async def main() -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/health")
        if resp.status_code != 200:
            raise SystemExit(f"/health failed: {resp.status_code}\n{resp.text}")
        lines.append("GET /health")
        lines.append(resp.text)

        resp = await client.get("/openapi.json")
        if resp.status_code != 200:
            raise SystemExit(f"/openapi.json failed: {resp.status_code}")
        OPENAPI_BEFORE.write_text(json.dumps(resp.json(), indent=2), encoding="utf-8")
        lines.append("GET /openapi.json (saved phase_9_9_openapi_before.json)")
        lines.append(f"status={resp.status_code} length={len(resp.text)}")

    lines.append("alembic current")
    alembic_current = run_cmd(["alembic", "current"])
    lines.append(alembic_current)
    lines.append("alembic heads")
    alembic_heads = run_cmd(["alembic", "heads"])
    lines.append(alembic_heads)
    ensure_at_head(alembic_current, alembic_heads)

    lines.append("git status -sb")
    lines.append(run_cmd(["git", "status", "-sb"]))
    lines.append("git log -1 --decorate")
    lines.append(run_cmd(["git", "log", "-1", "--decorate"]))

    PRE_FLIGHT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

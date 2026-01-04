"""Proof for Phase 4.11 external llm_json company discovery.

- Posts the llm-json payload twice to prove idempotency across sources,
  enrichments, prospects, and URL intake.
- Uses the mock fixture (no network) and asserts counts are stable on re-post.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import psycopg2
import requests
from dotenv import load_dotenv

sys.path.append(os.getcwd())
from app.core.config import settings  # noqa: E402

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_11_proof.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_11_openapi_head_after.txt"
ALEMBIC_ARTIFACT = ARTIFACT_DIR / "phase_4_11_alembic_after.txt"
GIT_ARTIFACT = ARTIFACT_DIR / "phase_4_11_git_after.txt"

FIXTURE_PATH = Path("scripts/proofs/fixtures/llm_json_mock_fixture.json")
ROOT_DIR = Path(__file__).resolve().parents[2]

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)


@dataclass
class Env:
    api_base: str
    tenant_id: str
    email: str
    password: str
    token: str


def load_env() -> Env:
    load_dotenv()
    api_base = (os.getenv("API_BASE", API_DEFAULT) or API_DEFAULT).strip()
    tenant_id = os.getenv("TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("EMAIL", EMAIL_DEFAULT)
    password = os.getenv("PASSWORD", PASSWORD_DEFAULT)
    token = login(api_base, tenant_id, email, password)
    return Env(api_base=api_base, tenant_id=tenant_id, email=email, password=password, token=token)


def login(api_base: str, tenant_id: str, email: str, password: str) -> str:
    resp = requests.post(
        urljoin(api_base, "/auth/login"),
        json={"email": email, "password": password},
        headers={"X-Tenant-ID": tenant_id},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login failed {resp.status_code}: {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("missing access_token")
    return token


def auth_headers(env: Env) -> dict[str, str]:
    return {"Authorization": f"Bearer {env.token}", "X-Tenant-ID": env.tenant_id}


def call_api(method: str, api_base: str, path: str, headers: dict[str, str], payload: Any | None = None) -> Any:
    url = urljoin(api_base, path)
    resp = requests.request(method, url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"API {method} {path} failed {resp.status_code}: {resp.text[:200]}")
    if resp.text:
        return resp.json()
    return None


def ensure_artifact_dir() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def write_artifact(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    log(f"wrote {path}")


def run_cmd(cmd: list[str]) -> str:
    import subprocess

    proc = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{output.strip()}")
    return output.strip()


def canonical_payload_hash(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def db_counts(run_id: str, tenant_id: str) -> dict[str, int]:
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM source_documents WHERE tenant_id=%s AND company_research_run_id=%s AND source_type='llm_json') AS llm_sources,
                  (SELECT COUNT(*) FROM ai_enrichment_record WHERE tenant_id=%s AND company_research_run_id=%s AND purpose='company_discovery') AS enrichments,
                  (SELECT COUNT(*) FROM company_prospects WHERE tenant_id=%s AND company_research_run_id=%s) AS prospects,
                  (SELECT COUNT(*) FROM source_documents WHERE tenant_id=%s AND company_research_run_id=%s AND source_type='url' AND (meta->>'origin')='llm_json') AS url_sources
                """,
                (tenant_id, run_id, tenant_id, run_id, tenant_id, run_id, tenant_id, run_id),
            )
            row = cur.fetchone()
            return {
                "llm_sources": row[0],
                "enrichments": row[1],
                "prospects": row[2],
                "url_sources": row[3],
            }


def fetch_openapi(env: Env) -> str:
    resp = requests.get(urljoin(env.api_base, "/openapi.json"), timeout=30)
    try:
        body = json.dumps(resp.json(), indent=2)
    except Exception:  # noqa: BLE001
        body = resp.text
    body_lines = body.splitlines()
    head = "\n".join(body_lines[:160])
    return f"Status: {resp.status_code}\n{head}"


def fetch_alembic_head() -> str:
    current = run_cmd([sys.executable, "-m", "alembic", "current"])
    heads = run_cmd([sys.executable, "-m", "alembic", "heads"])
    return f"alembic current:\n{current}\n\n---\n\nalembic heads:\n{heads}"


def git_status() -> str:
    import shutil

    git_exe = shutil.which("git") or "C:/Program Files/Git/bin/git.exe"
    if not Path(git_exe).exists():
        raise FileNotFoundError("git executable not found; ensure Git is installed and on PATH")

    status = run_cmd([git_exe, "status", "-sb"])
    log_head = run_cmd([git_exe, "log", "-1", "--decorate"])
    return f"git status -sb:\n{status}\n\n---\n\ngit log -1 --decorate:\n{log_head}"


def main() -> int:
    ensure_artifact_dir()
    env = load_env()

    openapi_head = fetch_openapi(env)
    write_artifact(OPENAPI_ARTIFACT, openapi_head)

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload_hash = canonical_payload_hash(fixture)
    log(f"fixture hash={payload_hash}")

    headers = auth_headers(env)

    # Create run
    run_name = f"LLM Discovery Proof {int(time.time())}"
    roles = call_api("GET", env.api_base, "/roles", headers)
    if not roles:
        raise RuntimeError("no roles available for tenant")
    role_id = roles[0]["id"]

    run = call_api(
        "POST",
        env.api_base,
        "/company-research/runs",
        headers,
        payload={
            "role_mandate_id": role_id,
            "name": run_name,
            "sector": "Facilities Management",
            "status": "planned",
        },
    )
    run_id = run["id"]
    log(f"created run {run_id}")

    before = db_counts(run_id, env.tenant_id)
    log(f"counts_before={before}")

    body = {
        "title": "Grok company discovery",
        "provider": "mock",
        "model": "mock",
        "purpose": "company_discovery",
        "payload": fixture,
    }

    first = call_api("POST", env.api_base, f"/company-research/runs/{run_id}/sources/llm-json", headers, payload=body)
    log(f"first_ingest={json.dumps(first, sort_keys=True)}")

    after_first = db_counts(run_id, env.tenant_id)
    log(f"counts_after_first={after_first}")

    second = call_api("POST", env.api_base, f"/company-research/runs/{run_id}/sources/llm-json", headers, payload=body)
    log(f"second_ingest={json.dumps(second, sort_keys=True)}")

    after_second = db_counts(run_id, env.tenant_id)
    log(f"counts_after_second={after_second}")

    assert second.get("skipped") is True, "duplicate post must be marked skipped"
    assert second.get("reason") == "duplicate_hash", "duplicate reason must be duplicate_hash"
    ingest_stats = second.get("ingest_stats") or {}
    for key in ["companies_new", "evidence_created", "urls_created"]:
        assert ingest_stats.get(key) == 0, f"ingest_stats.{key} must be 0 on duplicate"
    assert after_first == after_second, "idempotency failed: counts changed on duplicate post"

    write_artifact(LOG_ARTIFACT, "\n".join(LOG_LINES))
    write_artifact(ALEMBIC_ARTIFACT, fetch_alembic_head())
    try:
        git_out = git_status()
    except Exception as exc:  # noqa: BLE001
        git_out = f"git_error: {exc}"
        write_artifact(GIT_ARTIFACT, git_out)
        raise
    write_artifact(GIT_ARTIFACT, git_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

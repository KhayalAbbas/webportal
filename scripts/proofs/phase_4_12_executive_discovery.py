"""Proof for Phase 4.12 executive discovery

- Verifies gating: ingestion is rejected when no eligible companies exist.
- Ingests external executive llm_json payload once, then replays to prove idempotency.
- Uses the mock fixture only (no network).
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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_12_proof.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_12_openapi_after.txt"
ALEMBIC_ARTIFACT = ARTIFACT_DIR / "phase_4_12_alembic_after.txt"
GIT_ARTIFACT = ARTIFACT_DIR / "phase_4_12_git_after.txt"

FIXTURE_PATH = Path("scripts/proofs/fixtures/phase_4_12_exec_discovery_mock.json")
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


def call_api_raw(method: str, api_base: str, path: str, headers: dict[str, str], payload: Any | None = None) -> requests.Response:
    url = urljoin(api_base, path)
    return requests.request(method, url, headers=headers, json=payload, timeout=30)


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


def db_counts(run_id: str, tenant_id: str) -> dict[str, int]:
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM source_documents WHERE tenant_id=%s AND company_research_run_id=%s AND source_type='llm_json' AND (meta->>'purpose')='executive_discovery') AS llm_sources,
                  (SELECT COUNT(*) FROM ai_enrichment_record WHERE tenant_id=%s AND company_research_run_id=%s AND purpose='executive_discovery') AS enrichments,
                  (SELECT COUNT(*) FROM executive_prospects WHERE tenant_id=%s AND company_research_run_id=%s) AS executives,
                  (SELECT COUNT(*) FROM executive_prospect_evidence WHERE tenant_id=%s AND executive_prospect_id IN (SELECT id FROM executive_prospects WHERE tenant_id=%s AND company_research_run_id=%s)) AS exec_evidence,
                  (SELECT COUNT(*) FROM source_documents WHERE tenant_id=%s AND company_research_run_id=%s AND source_type='url' AND (meta->>'origin')='executive_llm_json') AS url_sources
                """,
                (tenant_id, run_id, tenant_id, run_id, tenant_id, run_id, tenant_id, tenant_id, run_id, tenant_id, run_id),
            )
            row = cur.fetchone()
            return {
                "llm_sources": row[0],
                "enrichments": row[1],
                "executives": row[2],
                "exec_evidence": row[3],
                "url_sources": row[4],
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
    return f"alembic current:\n{current}\n\n---\n\n" f"alembic heads:\n{heads}"


def git_status() -> str:
    import shutil

    git_exe = shutil.which("git") or "C:/Program Files/Git/bin/git.exe"
    status = run_cmd([git_exe, "status", "-sb"])
    log_head = run_cmd([git_exe, "log", "-1", "--decorate"])
    return f"git status -sb:\n{status}\n\n---\n\n git log -1 --decorate:\n{log_head}"


def main() -> int:
    ensure_artifact_dir()
    env = load_env()
    headers = auth_headers(env)

    openapi_head = fetch_openapi(env)
    write_artifact(OPENAPI_ARTIFACT, openapi_head)

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    log(f"fixture companies={[c.get('company_name') for c in fixture.get('companies', [])]}")

    roles = call_api("GET", env.api_base, "/roles", headers)
    if not roles:
        raise RuntimeError("no roles available for tenant")
    role_id = roles[0]["id"]

    run_name = f"Exec Discovery Proof {int(time.time())}"
    run = call_api(
        "POST",
        env.api_base,
        "/company-research/runs",
        headers,
        payload={
            "role_mandate_id": role_id,
            "name": run_name,
            "sector": "Metals",
            "status": "planned",
        },
    )
    run_id = run["id"]
    log(f"created run {run_id}")

    before = db_counts(run_id, env.tenant_id)
    log(f"counts_before={before}")

    body = {
        "title": "Executive discovery",
        "provider": "mock",
        "model": "mock",
        "payload": fixture,
    }

    # Gate should reject when no eligible companies exist
    resp = call_api_raw("POST", env.api_base, f"/company-research/runs/{run_id}/executive-discovery/run", headers, payload=body)
    log(f"gate_status={resp.status_code} gate_body={resp.text[:160]}")
    assert resp.status_code == 400, "expected gate to reject without eligible companies"

    # Create eligible prospect (accepted + exec_search_enabled)
    prospect = call_api(
        "POST",
        env.api_base,
        "/company-research/prospects",
        headers,
        payload={
            "company_research_run_id": run_id,
            "role_mandate_id": role_id,
            "name_raw": "Aurora Metals",
            "name_normalized": "aurora metals",
            "sector": "Metals",
            "status": "accepted",
            "exec_search_enabled": True,
        },
    )
    log(f"created prospect {prospect['id']}")

    first = call_api(
        "POST",
        env.api_base,
        f"/company-research/runs/{run_id}/executive-discovery/run",
        headers,
        payload=body,
    )
    log(f"first_ingest={json.dumps(first, sort_keys=True)}")

    after_first = db_counts(run_id, env.tenant_id)
    log(f"counts_after_first={after_first}")

    second = call_api(
        "POST",
        env.api_base,
        f"/company-research/runs/{run_id}/executive-discovery/run",
        headers,
        payload=body,
    )
    log(f"second_ingest={json.dumps(second, sort_keys=True)}")

    after_second = db_counts(run_id, env.tenant_id)
    log(f"counts_after_second={after_second}")

    external_result = second.get("external_result") or {}
    assert external_result.get("skipped") is True, "duplicate post must be marked skipped"
    ingest_stats = external_result.get("ingest_stats") or second.get("ingest_stats") or {}
    for key in ["executives_new", "evidence_created", "urls_created"]:
        assert ingest_stats.get(key) == 0, f"ingest_stats.{key} must be 0 on duplicate"
    assert after_first == after_second, "idempotency failed: counts changed on duplicate post"

    write_artifact(LOG_ARTIFACT, "\n".join(LOG_LINES))
    write_artifact(ALEMBIC_ARTIFACT, fetch_alembic_head())
    write_artifact(GIT_ARTIFACT, git_status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

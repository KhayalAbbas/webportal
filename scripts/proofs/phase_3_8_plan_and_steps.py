#!/usr/bin/env python3
"""Phase 3.8 proof: sources-driven plan with list/proposal ingestion."""

import os
import sys
import json
import uuid
import subprocess
import asyncio
from urllib.parse import urljoin

import requests
import psycopg2
from dotenv import load_dotenv

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

LIST_A_TEXT = """Acme Holdings
Beta Group
"""

LIST_B_TEXT = """Gamma Logistics
Acme Holdings
"""

PROPOSAL_JSON = {
    "query": "phase 3.8 proof query",
    "sources": [
        {
            "temp_id": "src_1",
            "title": "AI Summary",
            "url": "https://example.com/proposal",
            "provider": "proof",
        }
    ],
    "companies": [
        {
            "name": "Acme Holdings",
            "aliases": [
                {"name": "Acme Holdings Intl", "type": "legal", "confidence": 0.8}
            ],
            "metrics": [
                {
                    "key": "total_assets",
                    "type": "number",
                    "value": 1000000,
                    "currency": "USD",
                    "unit": "usd",
                    "source_temp_id": "src_1",
                    "evidence_snippet": "Reported assets",
                }
            ],
            "website_url": "https://acme.example.com",
            "hq_country": "US",
            "hq_city": "New York",
            "sector": "industrial",
            "ai_rank": 1,
            "ai_score": 0.9,
            "evidence_snippets": ["AI proposal evidence"],
            "source_sha256s": ["abc123"],
        }
    ],
}


def db_connect():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        database=os.getenv("DB_NAME", "ats_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
    conn.autocommit = True
    return conn


def select_role_id(tenant_id: str) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM role WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 1",
        (tenant_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise RuntimeError("No role found for tenant")
    return str(row[0])


def login_api(api_base: str, tenant_id: str, email: str, password: str) -> str:
    login_url = urljoin(api_base, "/auth/login")
    resp = requests.post(
        login_url,
        json={"email": email, "password": password},
        headers={"X-Tenant-ID": tenant_id},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API login failed: {resp.status_code} {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Missing access_token")
    return token


def call_api(method: str, url: str, headers: dict, payload=None):
    return requests.request(method, url, headers=headers, json=payload, timeout=20)


def create_run(api_base: str, tenant_id: str, headers: dict) -> str:
    role_id = select_role_id(tenant_id)
    payload = {
        "role_mandate_id": role_id,
        "name": f"phase-3-8-proof-{uuid.uuid4().hex[:6]}",
        "description": "Phase 3.8 source ingestion proof run",
        "sector": "general",
        "status": "planned",
    }
    url = urljoin(api_base, "/company-research/runs")
    resp = call_api("POST", url, headers, payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Create run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def add_list_source(api_base: str, run_id: str, headers: dict, title: str, content_text: str) -> str:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/sources/list")
    resp = call_api("POST", url, headers, {"title": title, "content_text": content_text})
    if resp.status_code != 200:
        raise RuntimeError(f"Add list source failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def add_proposal_source(api_base: str, run_id: str, headers: dict, proposal: dict) -> str:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/sources/proposal")
    resp = call_api("POST", url, headers, {"title": "AI Proposal", "content_text": json.dumps(proposal)})
    if resp.status_code != 200:
        raise RuntimeError(f"Add proposal source failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def start_run(api_base: str, run_id: str, headers: dict) -> str:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/start")
    resp = call_api("POST", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Start failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def get_steps(api_base: str, run_id: str, headers: dict) -> list:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/steps")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Steps fetch failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def get_run(api_base: str, run_id: str, headers: dict) -> dict:
    url = urljoin(api_base, f"/company-research/runs/{run_id}")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Get run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def get_sources(api_base: str, run_id: str, headers: dict) -> list:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/sources")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Sources fetch failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def run_worker_once() -> int:
    try:
        from app.workers.company_research_worker import run_worker
    except ImportError:
        cmd = [sys.executable, "-m", "app.workers.company_research_worker", "--once"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr)
        return proc.returncode

    return asyncio.run(run_worker(loop=False, sleep_seconds=1))


def ensure_step_status(steps: list, step_key: str, expected: str) -> bool:
    for s in steps:
        if s.get("step_key") == step_key:
            return s.get("status") == expected
    return False


def count_prospects_and_evidence(tenant_id: str, run_id: str) -> tuple[int, int]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM company_prospects WHERE tenant_id=%s AND company_research_run_id=%s",
        (tenant_id, run_id),
    )
    prospects = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM company_prospect_evidence WHERE tenant_id=%s AND company_prospect_id IN (SELECT id FROM company_prospects WHERE tenant_id=%s AND company_research_run_id=%s)",
        (tenant_id, tenant_id, run_id),
    )
    evidence = cur.fetchone()[0]
    cur.close()
    conn.close()
    return prospects, evidence


def main() -> int:
    load_dotenv()
    api_base = os.getenv("API_BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)

    print("=== PHASE 3.8 PLAN AND INGEST PROOF ===")
    print(f"API Base URL: {api_base}")
    print(f"Tenant ID: {tenant_id}")

    token = login_api(api_base, tenant_id, email, password)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

    run_id = create_run(api_base, tenant_id, headers)
    print(f"Run created: {run_id}")

    list_source_ids = [
        add_list_source(api_base, run_id, headers, "List A", LIST_A_TEXT),
        add_list_source(api_base, run_id, headers, "List B", LIST_B_TEXT),
    ]
    print(f"Attached list sources: {list_source_ids}")

    proposal_source_id = add_proposal_source(api_base, run_id, headers, PROPOSAL_JSON)
    print(f"Attached proposal source: {proposal_source_id}")

    job_id = start_run(api_base, run_id, headers)
    print(f"Run started (job {job_id})")

    # Run worker up to 10 passes until run succeeds
    for _ in range(10):
        rc = run_worker_once()
        if rc != 0:
            print("Worker returned non-zero")
            return 1
        run_obj = get_run(api_base, run_id, headers)
        if run_obj.get("status") == "succeeded":
            break
    else:
        print("Run did not reach succeeded after worker passes")
        return 1

    steps_after = get_steps(api_base, run_id, headers)
    for key in ("process_sources", "ingest_lists", "ingest_proposal", "finalize"):
        if not ensure_step_status(steps_after, key, "succeeded"):
            print(f"Step {key} not succeeded")
            return 1

    prospects, evidence = count_prospects_and_evidence(tenant_id, run_id)
    if prospects == 0 or evidence == 0:
        print(f"Unexpected counts: prospects={prospects} evidence={evidence}")
        return 1

    # Idempotency: one more worker tick should be a no-op
    rc_last = run_worker_once()
    if rc_last != 0:
        print("Idempotency worker tick failed")
        return 1
    steps_final = get_steps(api_base, run_id, headers)
    if steps_after != steps_final:
        print("Step list changed after idempotent tick")
        return 1

    print("=== VALIDATION PASSED ===")
    print(f"RUN_ID={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

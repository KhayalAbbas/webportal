#!/usr/bin/env python3
"""Phase 3.7 proof: deterministic plan + step runner."""

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
TEST_URL = "https://example.com/"


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


def login_ui(session: requests.Session, api_base: str, tenant_id: str, email: str, password: str) -> None:
    resp = session.post(
        urljoin(api_base, "/login"),
        data={"email": email, "password": password, "tenant_id": tenant_id},
        allow_redirects=False,
        timeout=10,
    )
    if resp.status_code not in {200, 303}:  # login redirects on success
        raise RuntimeError(f"UI login failed: {resp.status_code} {resp.text[:200]}")
    if "session" not in session.cookies:
        raise RuntimeError("UI login did not set session cookie")


def call_api(method: str, url: str, headers: dict, payload=None):
    return requests.request(method, url, headers=headers, json=payload, timeout=20)


def create_run(api_base: str, tenant_id: str, headers: dict) -> str:
    role_id = select_role_id(tenant_id)
    payload = {
        "role_mandate_id": role_id,
        "name": f"phase-3-7-proof-{uuid.uuid4().hex[:6]}",
        "description": "Phase 3.7 plan/steps proof run",
        "sector": "general",
        "status": "planned",
    }
    url = urljoin(api_base, "/company-research/runs")
    resp = call_api("POST", url, headers, payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Create run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def add_url_source_ui(session: requests.Session, api_base: str, run_id: str, source_url: str) -> None:
    url = urljoin(api_base, f"/ui/company-research/runs/{run_id}/sources/add-url")
    resp = session.post(
        url,
        data={"url": source_url, "title": "Phase 3.7 proof source"},
        allow_redirects=False,
        timeout=10,
    )
    if resp.status_code not in {200, 303}:
        raise RuntimeError(f"Add URL source failed: {resp.status_code} {resp.text[:200]}")


def start_run(api_base: str, run_id: str, headers: dict) -> str:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/start")
    resp = call_api("POST", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Start failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def get_plan(api_base: str, run_id: str, headers: dict) -> dict:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/plan")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Plan fetch failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


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


def main() -> int:
    load_dotenv()
    api_base = os.getenv("API_BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)

    print("=== PHASE 3.7 PLAN AND STEPS PROOF ===")
    print(f"API Base URL: {api_base}")
    print(f"Tenant ID: {tenant_id}")

    token = login_api(api_base, tenant_id, email, password)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

    ui_session = requests.Session()
    login_ui(ui_session, api_base, tenant_id, email, password)

    run_id = create_run(api_base, tenant_id, headers)
    print(f"Run created: {run_id}")

    add_url_source_ui(ui_session, api_base, run_id, TEST_URL)
    print("Added URL source via UI endpoint")

    job_id = start_run(api_base, run_id, headers)
    print(f"Run started (job {job_id})")

    plan = get_plan(api_base, run_id, headers)
    if not plan.get("locked_at"):
        print("Plan not locked after start")
        return 1
    steps = get_steps(api_base, run_id, headers)
    step_keys = [s.get("step_key") for s in steps]
    if "process_sources" not in step_keys or "finalize" not in step_keys:
        print(f"Steps missing expected keys: {step_keys}")
        return 1

    # Run worker up to 8 passes until run succeeds
    for _ in range(8):
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
    if not ensure_step_status(steps_after, "process_sources", "succeeded"):
        print("process_sources step not succeeded")
        return 1
    if not ensure_step_status(steps_after, "finalize", "succeeded"):
        print("finalize step not succeeded")
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

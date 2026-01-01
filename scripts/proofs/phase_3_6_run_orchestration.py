#!/usr/bin/env python3
"""Phase 3.6 run orchestration proof.

Steps:
1) Login and create two runs (success + cancel).
2) For success run: start twice (idempotent), worker -> expect succeeded with claimed+completed.
3) For cancel run: start twice, cancel before worker, worker -> expect cancelled with claimed+cancelled (not failed).
"""

import os
import sys
import json
import uuid
import subprocess
import asyncio
from typing import Optional
from urllib.parse import urljoin

import requests
import psycopg2
from dotenv import load_dotenv

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"


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


def call_api(method: str, url: str, headers: dict, payload=None):
    resp = requests.request(method, url, headers=headers, json=payload, timeout=20)
    return resp


def login(api_base: str, tenant_id: str, email: str, password: str):
    login_url = urljoin(api_base, "/auth/login")
    resp = requests.post(
        login_url,
        json={"email": email, "password": password},
        headers={"X-Tenant-ID": tenant_id},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.status_code} {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Missing access_token")
    return token


def create_run(api_base: str, tenant_id: str, headers: dict) -> str:
    role_id = select_role_id(tenant_id)
    payload = {
        "role_mandate_id": role_id,
        "name": f"phase-3-6-proof-{uuid.uuid4().hex[:6]}",
        "description": "Phase 3.6 worker proof run",
        "sector": "general",
        "status": "planned",
    }
    url = urljoin(api_base, "/company-research/runs")
    resp = call_api("POST", url, headers, payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Create run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def start_run(api_base: str, run_id: str, headers: dict) -> str:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/start")
    resp = call_api("POST", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Start failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def cancel_run(api_base: str, run_id: str, headers: dict) -> None:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/cancel")
    resp = call_api("POST", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Cancel failed: {resp.status_code} {resp.text[:200]}")


def get_run(api_base: str, run_id: str, headers: dict) -> dict:
    url = urljoin(api_base, f"/company-research/runs/{run_id}")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Get run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def get_events(api_base: str, run_id: str, headers: dict) -> list:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/events")
    resp = call_api("GET", url, headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Get events failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def run_worker_once() -> int:
    try:
        from app.workers.company_research_worker import run_worker
    except ImportError as exc:  # Defensive: subprocess fallback if import fails
        cmd = [sys.executable, "-m", "app.workers.company_research_worker", "--once"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr)
        return proc.returncode

    # Prefer in-process worker run to avoid subprocess env issues
    return asyncio.run(run_worker(loop=False, sleep_seconds=1))


def ensure_event(events: list, event_type: str, disallow_status: Optional[str] = None) -> bool:
    for e in events:
        if e.get("event_type") == event_type:
            if disallow_status and e.get("status") == disallow_status:
                return False
            return True
    return False


def main():
    load_dotenv()
    api_base = os.getenv("API_BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)

    print("=== PHASE 3.6 RUN ORCHESTRATION PROOF ===")
    print(f"API Base URL: {api_base}")
    print(f"Tenant ID: {tenant_id}")

    token = login(api_base, tenant_id, email, password)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

    print("Creating runs...")
    run_success_id = create_run(api_base, tenant_id, headers)
    run_cancel_id = create_run(api_base, tenant_id, headers)
    print(f"Run (success path): {run_success_id}")
    print(f"Run (cancel path): {run_cancel_id}")

    # ==============================
    # Success path
    # ==============================
    job_s1 = start_run(api_base, run_success_id, headers)
    job_s1b = start_run(api_base, run_success_id, headers)
    if job_s1b != job_s1:
        print(" Success run: second start returned different active job")
        return 1
    print(f" Success run start idempotent (job {job_s1})")

    rc_success = run_worker_once()
    if rc_success != 0:
        print(" Worker failed on success run")
        return 1

    run_success = get_run(api_base, run_success_id, headers)
    if run_success.get("status") != "succeeded":
        # One more attempt in case processing overlapped
        rc_success_retry = run_worker_once()
        if rc_success_retry != 0:
            print(" Worker retry failed on success run")
            return 1
        run_success = get_run(api_base, run_success_id, headers)

    if run_success.get("status") != "succeeded":
        print(f" Success run did not finish as succeeded (status={run_success.get('status')})")
        return 1
    print(f" Success run status: {run_success.get('status')}")

    events_success = get_events(api_base, run_success_id, headers)
    if not events_success:
        print(" Success run: no events recorded")
        return 1
    if not ensure_event(events_success, "worker_claimed"):
        print(" Success run: missing worker_claimed event")
        return 1
    if not ensure_event(events_success, "worker_completed"):
        print(" Success run: missing worker_completed event")
        return 1
    print(f" Success run events: {len(events_success)} recorded")

    # ==============================
    # Cancel path
    # ==============================
    job_c1 = start_run(api_base, run_cancel_id, headers)
    job_c1b = start_run(api_base, run_cancel_id, headers)
    if job_c1b != job_c1:
        print(" Cancel run: second start returned different active job")
        return 1
    print(f" Cancel run start idempotent (job {job_c1})")

    cancel_run(api_base, run_cancel_id, headers)
    print("Requested cancel before worker")

    rc_cancel = run_worker_once()
    if rc_cancel != 0:
        print(" Worker failed on cancel run")
        return 1

    run_cancel = get_run(api_base, run_cancel_id, headers)
    if run_cancel.get("status") != "cancelled":
        # Try one more worker tick if still queued/running
        if run_cancel.get("status") in {"queued", "running", "cancel_requested"}:
            rc_cancel_retry = run_worker_once()
            if rc_cancel_retry != 0:
                print(" Worker retry failed on cancel run")
                return 1
            run_cancel = get_run(api_base, run_cancel_id, headers)

    if run_cancel.get("status") != "cancelled":
        print(f" Cancel run did not reach cancelled (status={run_cancel.get('status')})")
        return 1
    print(f" Cancel run status: {run_cancel.get('status')}")

    events_cancel = get_events(api_base, run_cancel_id, headers)
    if not events_cancel:
        print(" Cancel run: no events recorded")
        return 1
    if not ensure_event(events_cancel, "worker_claimed"):
        print(" Cancel run: missing worker_claimed event")
        return 1
    if not ensure_event(events_cancel, "worker_cancelled", disallow_status="failed"):
        print(" Cancel run: missing worker_cancelled event or status indicates failure")
        return 1
    print(f" Cancel run events: {len(events_cancel)} recorded")

    print("=== VALIDATION PASSED ===")
    print(f"RUN_SUCCESS_ID={run_success_id}")
    print(f"RUN_CANCEL_ID={run_cancel_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

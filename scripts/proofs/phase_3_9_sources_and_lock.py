#!/usr/bin/env python3
"""Phase 3.9 proof: sources listing + lock enforcement after start/plan lock."""

import os
import sys
import uuid
import json
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

LIST_TEXT = """Acme Holdings\nBeta Group\n"""


def login_api(api_base: str, tenant_id: str, email: str, password: str) -> str:
    resp = requests.post(
        urljoin(api_base, "/auth/login"),
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


def call_api(method: str, url: str, headers: dict, payload=None) -> requests.Response:
    return requests.request(method, url, headers=headers, json=payload, timeout=15)


def select_role_id(api_base: str, tenant_id: str, headers: dict) -> str:
    resp = call_api("GET", urljoin(api_base, "/roles"), headers)
    if resp.status_code != 200:
        raise RuntimeError(f"List roles failed: {resp.status_code} {resp.text[:200]}")
    roles = resp.json()
    if not roles:
        raise RuntimeError("No roles returned")
    return roles[0]["id"]


def create_run(api_base: str, tenant_id: str, headers: dict) -> str:
    role_id = select_role_id(api_base, tenant_id, headers)
    payload = {
        "role_mandate_id": role_id,
        "name": f"phase-3-9-proof-{uuid.uuid4().hex[:6]}",
        "description": "Phase 3.9 sources + lock proof",
        "sector": "general",
        "status": "planned",
    }
    resp = call_api("POST", urljoin(api_base, "/company-research/runs"), headers, payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Create run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def add_list_source(api_base: str, run_id: str, headers: dict, title: str, content_text: str) -> requests.Response:
    url = urljoin(api_base, f"/company-research/runs/{run_id}/sources/list")
    return call_api("POST", url, headers, {"title": title, "content_text": content_text})


def start_run(api_base: str, run_id: str, headers: dict) -> str:
    resp = call_api("POST", urljoin(api_base, f"/company-research/runs/{run_id}/start"), headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Start run failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()["id"]


def get_plan(api_base: str, run_id: str, headers: dict) -> dict:
    resp = call_api("GET", urljoin(api_base, f"/company-research/runs/{run_id}/plan"), headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Plan fetch failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def get_sources(api_base: str, run_id: str, headers: dict) -> list:
    resp = call_api("GET", urljoin(api_base, f"/company-research/runs/{run_id}/sources"), headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Sources fetch failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def main() -> int:
    load_dotenv()
    api_base = os.getenv("API_BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)

    print("=== PHASE 3.9 SOURCES + LOCK PROOF ===")
    print(f"API Base: {api_base}")
    print(f"Tenant: {tenant_id}")

    token = login_api(api_base, tenant_id, email, password)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

    run_id = create_run(api_base, tenant_id, headers)
    print(f"Run created: {run_id}")

    pre_source_resp = add_list_source(api_base, run_id, headers, "Pre-start List", LIST_TEXT)
    if pre_source_resp.status_code != 200:
        print(pre_source_resp.text)
        raise RuntimeError(f"Pre-start source add failed: {pre_source_resp.status_code}")
    pre_source_id = pre_source_resp.json()["id"]
    print(f"Pre-start source attached: {pre_source_id}")

    sources_before = get_sources(api_base, run_id, headers)
    print(f"Sources before start: {len(sources_before)}")

    job_id = start_run(api_base, run_id, headers)
    print(f"Run started (job {job_id})")

    plan = get_plan(api_base, run_id, headers)
    locked_at = plan.get("locked_at")
    if not locked_at:
        raise RuntimeError("Plan not locked after start")
    print(f"Plan locked_at: {locked_at}")

    locked_resp = add_list_source(api_base, run_id, headers, "Post-start List", "Should fail")
    if locked_resp.status_code != 409:
        print(locked_resp.text)
        raise RuntimeError(f"Expected 409 after lock, got {locked_resp.status_code}")
    detail = locked_resp.json().get("detail")
    print(f"Locked add response: {detail}")

    sources_after = get_sources(api_base, run_id, headers)
    if len(sources_after) != len(sources_before):
        raise RuntimeError("Source count changed after locked attempt")
    print(f"Sources after locked attempt: {len(sources_after)} (unchanged)")

    print("=== VALIDATION PASSED ===")
    print(f"RUN_ID={run_id}")
    print(f"JOB_ID={job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

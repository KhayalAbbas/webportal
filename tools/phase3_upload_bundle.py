#!/usr/bin/env python3
"""
Phase 3 Bundle Upload Tool

Simple CLI tool for uploading RunBundle JSON files to the Phase 3 API.
Supports creating new research runs or uploading to existing runs.
"""

import argparse
import json
import hashlib
import sys
import os
from typing import Dict, Any, List, Set
import httpx


def compute_sha256(text: str) -> str:
    """Compute SHA256 hash of UTF-8 encoded text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate_bundle(bundle: Dict[str, Any]) -> List[str]:
    """
    Validate bundle JSON locally before upload.
    Returns list of validation errors (empty if valid).
    """
    errors = []
    
    # Check version
    if bundle.get("version") != "run_bundle_v1":
        errors.append(f"Invalid version: {bundle.get('version')}. Expected 'run_bundle_v1'")
    
    # Validate steps
    valid_step_types = {"search", "fetch", "extract", "validate", "compose", "finalize"}
    valid_statuses = {"queued", "running", "ok", "failed", "skipped"}
    
    steps = bundle.get("steps", [])
    for i, step in enumerate(steps):
        step_type = step.get("step_type")
        status = step.get("status")
        
        if step_type not in valid_step_types:
            errors.append(f"Step {i+1}: Invalid step_type '{step_type}'. Must be one of {valid_step_types}")
        
        if status not in valid_statuses:
            errors.append(f"Step {i+1}: Invalid status '{status}'. Must be one of {valid_statuses}")
    
    # Validate sources
    sources = bundle.get("sources", [])
    source_sha256s = set()
    
    for i, source in enumerate(sources):
        content_text = source.get("content_text", "")
        declared_sha256 = source.get("sha256", "")
        
        if not content_text:
            errors.append(f"Source {i+1}: content_text is empty")
            continue
        
        computed_sha256 = compute_sha256(content_text)
        source_sha256s.add(declared_sha256)
        
        if computed_sha256 != declared_sha256:
            errors.append(f"Source {i+1}: SHA256 mismatch. Computed: {computed_sha256}, Declared: {declared_sha256}")
    
    # Validate companies in proposal_json
    proposal_json = bundle.get("proposal_json", {})
    companies = proposal_json.get("companies", [])
    
    for i, company in enumerate(companies):
        evidence_snippets = company.get("evidence_snippets", [])
        company_source_sha256s = company.get("source_sha256s", [])
        
        if len(evidence_snippets) < 1:
            errors.append(f"Company {i+1}: Must have at least 1 evidence_snippet")
        
        if len(company_source_sha256s) < 1:
            errors.append(f"Company {i+1}: Must have at least 1 source_sha256")
        
        # Check that all referenced SHA256s exist in sources
        for sha256 in company_source_sha256s:
            if sha256 not in source_sha256s:
                errors.append(f"Company {i+1}: References SHA256 '{sha256}' not found in sources")
    
    return errors


async def create_research_run(base_url: str, objective: str, idempotency_key: str = None, headers: Dict[str, str] = None) -> str:
    """Create a new research run and return the run_id."""
    payload = {
        "objective": objective,
        "constraints": {},
        "rank_spec": {}
    }
    
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/runs/",
            json=payload,
            headers=headers or {},
            follow_redirects=True
        )
    
    if response.status_code == 201:
        data = response.json()
        run_id = data['id']
        print(f"Created research run: {run_id}")
        return run_id
    else:
        print(f"ERROR: Failed to create research run (HTTP {response.status_code})")
        print(f"Response: {response.text}")
        sys.exit(1)


async def upload_bundle(base_url: str, run_id: str, bundle: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Upload bundle to the specified run."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/api/runs/{run_id}/bundle",
            json=bundle,
            headers=headers or {},
            follow_redirects=True
        )
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"ERROR: Failed to upload bundle (HTTP {response.status_code})")
        print(f"Response: {response.text}")
        sys.exit(1)


async def verify_run(base_url: str, run_id: str, headers: Dict[str, str] = None):
    """Verify run status and steps."""
    async with httpx.AsyncClient() as client:
        # Get run details
        run_response = await client.get(
            f"{base_url}/api/runs/{run_id}",
            headers=headers or {}
        )
        
        if run_response.status_code != 200:
            print(f"ERROR: Failed to get run details (HTTP {run_response.status_code})")
            return
        
        run_data = run_response.json()
        print(f"Run status: {run_data.get('status')}")
        
        # Get steps
        steps_response = await client.get(
            f"{base_url}/api/runs/{run_id}/steps",
            headers=headers or {}
        )
        
        if steps_response.status_code == 200:
            steps_data = steps_response.json()
            if isinstance(steps_data, list):
                steps = steps_data
            else:
                steps = steps_data.get('steps', [])
            print(f"Steps: {len(steps)} total")
            for step in steps:
                print(f"  - {step.get('step_key')}: {step.get('step_type')} ({step.get('status')})")
        else:
            print(f"WARNING: Could not retrieve steps (HTTP {steps_response.status_code})")


def get_auth_headers(token: str = None, tenant_id: str = None) -> Dict[str, str]:
    """Get authentication headers if token is provided."""
    headers = {"Content-Type": "application/json"}
    
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    
    return headers


async def login_and_get_token(base_url: str, email: str, password: str, tenant_id: str) -> str:
    """Login and get JWT token."""
    credentials = {
        "email": email,
        "password": password
    }
    
    headers = {"Content-Type": "application/json", "X-Tenant-ID": tenant_id}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/auth/login",
            json=credentials,
            headers=headers
        )
    
    if response.status_code == 200:
        data = response.json()
        return data["access_token"]
    else:
        print(f"ERROR: Login failed (HTTP {response.status_code})")
        print(f"Response: {response.text}")
        sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Upload Phase 3 RunBundle JSON to API")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--bundle", required=True, help="Path to bundle JSON file")
    parser.add_argument("--run-id", help="Existing run ID (if not provided, creates new run)")
    parser.add_argument("--objective", help="Objective for new run (required if --run-id not provided)")
    parser.add_argument("--idempotency-key", help="Idempotency key for new run")
    parser.add_argument("--no-verify", action="store_true", help="Skip verification step")
    parser.add_argument("--login", action="store_true", help="Login using env vars ATS_EMAIL/ATS_PASSWORD/ATS_TENANT_ID")
    
    args = parser.parse_args()
    
    # Validation
    if not args.run_id and not args.objective:
        print("ERROR: Either --run-id or --objective must be provided")
        sys.exit(1)
    
    # Load bundle JSON
    try:
        with open(args.bundle, 'r', encoding='utf-8') as f:
            bundle = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Bundle file not found: {args.bundle}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in bundle file: {e}")
        sys.exit(1)
    
    # Get authentication token from environment or login
    token = os.getenv("ATS_TOKEN")
    tenant_id = os.getenv("ATS_TENANT_ID", "b3909011-8bd3-439d-a421-3b70fae124e9")
    
    if args.login:
        email = os.getenv("ATS_EMAIL")
        password = os.getenv("ATS_PASSWORD")
        
        if not email or not password:
            print("ERROR: --login requires ATS_EMAIL and ATS_PASSWORD environment variables")
            sys.exit(1)
        
        print(f"Logging in as {email}...")
        token = await login_and_get_token(args.base_url, email, password, tenant_id)
        print("✓ Login successful")
    
    headers = get_auth_headers(token, tenant_id)
    
    # Determine run_id
    if args.run_id:
        run_id = args.run_id
        print(f"Using existing run: {run_id}")
    else:
        run_id = await create_research_run(args.base_url, args.objective, args.idempotency_key, headers)
    
    # Force bundle run_id to match
    bundle["run_id"] = run_id
    
    # Local validation
    print("Validating bundle locally...")
    validation_errors = validate_bundle(bundle)
    
    if validation_errors:
        print("VALIDATION ERRORS:")
        for error in validation_errors:
            print(f"  - {error}")
        sys.exit(1)
    
    print("Bundle validation passed")
    
    # Upload bundle
    print(f"Uploading bundle to run {run_id}...")
    upload_result = await upload_bundle(args.base_url, run_id, bundle, headers)
    
    print("Upload response:")
    print(json.dumps(upload_result, indent=2))
    
    # Verification
    if not args.no_verify:
        print("\nVerifying run status...")
        await verify_run(args.base_url, run_id, headers)
    
    print("\nSuccess!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
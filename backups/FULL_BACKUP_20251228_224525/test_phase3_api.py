#!/usr/bin/env python
"""
Phase 3 API Testing Script

This script:
1. Creates a ResearchRun via POST /api/runs
2. Builds a valid RunBundle JSON according to the audited implementation 
3. Uploads the bundle via POST /api/runs/{run_id}/bundle
4. Verifies the run status and steps

Requirements match the audited implementation:
- steps[].step_type in: search, fetch, extract, validate, compose, finalize
- steps[].status in: queued, running, ok, failed, skipped
- sources[].content_text must be non-empty
- sources[].sha256 must equal SHA256(content_text UTF-8)
- each proposal_json.companies[] must include evidence_snippets (>=1) and source_sha256s (>=1)
- every sha256 in company.source_sha256s must exist in sources[].sha256
- run_id in JSON must match run_id in upload URL
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
import httpx


# Configuration
BASE_URL = "http://127.0.0.1:8000"
TENANT_ID = "b3909011-8bd3-439d-a421-3b70fae124e9"

# Test credentials from the test_authentication script
ADMIN_CREDENTIALS = {"email": "admin@test.com", "password": "admin123"}


async def login() -> str:
    """Login and return access token."""
    print(f"→ Logging in as {ADMIN_CREDENTIALS['email']}...")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/login",
            json=ADMIN_CREDENTIALS,
            headers={"X-Tenant-ID": TENANT_ID}
        )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Login successful!")
        print(f"  User: {data['user']['full_name']}")
        print(f"  Role: {data['user']['role']}")
        print(f"  Token: {data['access_token'][:50]}...")
        return data['access_token']
    else:
        print(f"✗ Login failed: {response.status_code}")
        print(f"  Response: {response.text}")
        return None


def get_headers(token: str) -> dict:
    """Get headers with authentication token."""
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


async def create_research_run(token: str) -> str:
    """Create a ResearchRun via POST /api/runs and return run_id."""
    print("\n→ Creating ResearchRun...")
    
    payload = {
        "objective": "Test run bundle upload",
        "constraints": {},
        "rank_spec": {},
        "idempotency_key": "phase3_smoke_test_runbundle"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/runs/",
            json=payload,
            headers=get_headers(token),
            follow_redirects=True
        )
    
    if response.status_code == 201:
        data = response.json()
        run_id = data['id']
        print(f"✓ ResearchRun created successfully!")
        print(f"  Run ID: {run_id}")
        print(f"  Status: {data['status']}")
        print(f"  Objective: {data['objective']}")
        return run_id
    else:
        print(f"✗ Failed to create ResearchRun: {response.status_code}")
        print(f"  Response: {response.text}")
        return None


def compute_sha256(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def build_run_bundle(run_id: str) -> dict:
    """Build a valid RunBundle JSON object."""
    print("\n→ Building RunBundle JSON...")
    
    # Source content
    content_text = "Example content"
    sha256_hash = compute_sha256(content_text)
    
    print(f"  Content: '{content_text}'")
    print(f"  SHA256: {sha256_hash}")
    
    # Build bundle according to the audited implementation requirements
    bundle = {
        "version": "run_bundle_v1",
        "run_id": run_id,
        "plan_json": {"steps": 1},
        "steps": [
            {
                "step_key": "s1",
                "step_type": "validate",  # Must be one of: search, fetch, extract, validate, compose, finalize
                "status": "ok",  # Must be one of: queued, running, ok, failed, skipped
                "inputs_json": {},
                "outputs_json": {},
                "provider_meta": {},
                "started_at": None,
                "finished_at": None,
                "output_sha256": None,
                "error": None
            }
        ],
        "sources": [
            {
                "sha256": sha256_hash,
                "url": "https://example.com/source1",
                "retrieved_at": "2024-12-27T10:00:00Z",
                "mime_type": "text/html",
                "title": "Example Source",
                "content_text": content_text,  # Must be non-empty
                "meta": {"provider": "tester"}
            }
        ],
        "proposal_json": {
            "query": "Test companies for Phase 3",
            "sources": [
                {
                    "temp_id": "source_1",
                    "title": "Example Source",
                    "url": "https://example.com/source1",
                    "provider": "tester",
                    "fetched_at": "2024-12-27T10:00:00Z"
                }
            ],
            "companies": [
                {
                    "name": "Demo Co",
                    "aliases": [],
                    "metrics": [
                        {
                            "key": "fleet_size",
                            "type": "number",
                            "value": 1.0,
                            "source_temp_id": "source_1",
                            "evidence_snippet": "evidence"
                        }
                    ],
                    "website_url": None,
                    "hq_country": None,
                    "hq_city": None,
                    "sector": None,
                    "description": None,
                    "ai_rank": None,
                    "ai_score": None,
                    # Required fields per audited implementation
                    "evidence_snippets": ["evidence"],  # Must have >=1 item
                    "source_sha256s": [sha256_hash]  # Must have >=1 item, must exist in sources[].sha256
                }
            ],
            "generated_at": "2024-12-27T10:00:00Z",
            "model": "test"
        }
    }
    
    print(f"✓ RunBundle built with run_id: {run_id}")
    return bundle


def save_bundle_to_disk(bundle: dict, filepath: str):
    """Save bundle JSON to disk."""
    print(f"\n→ Saving bundle to {filepath}...")
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2, default=str)
    
    print(f"✓ Bundle saved to {filepath}")


async def upload_bundle(token: str, run_id: str, bundle: dict):
    """Upload bundle via POST /api/runs/{run_id}/bundle."""
    print(f"\n→ Uploading bundle to run {run_id}...")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/runs/{run_id}/bundle",
            json=bundle,
            headers=get_headers(token)
        )
    
    print(f"  HTTP Status: {response.status_code}")
    print(f"  Response: {response.text}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Bundle uploaded successfully!")
        print(f"  Bundle SHA256: {data.get('bundle_sha256')}")
        print(f"  Status: {data.get('status')}")
        print(f"  Already accepted: {data.get('already_accepted', False)}")
        return True
    else:
        print(f"✗ Bundle upload failed: {response.status_code}")
        return False


async def verify_run_status(token: str, run_id: str):
    """Verify run status and steps."""
    print(f"\n→ Verifying run status for {run_id}...")
    
    async with httpx.AsyncClient() as client:
        # Get run details
        run_response = await client.get(
            f"{BASE_URL}/api/runs/{run_id}",
            headers=get_headers(token)
        )
        
        # Get steps
        steps_response = await client.get(
            f"{BASE_URL}/api/runs/{run_id}/steps",
            headers=get_headers(token)
        )
    
    if run_response.status_code == 200:
        run_data = run_response.json()
        print(f"✓ Run details retrieved!")
        print(f"  Status: {run_data['status']}")
        print(f"  Bundle SHA256: {run_data.get('bundle_sha256', 'None')}")
        print(f"  Plan JSON: {run_data.get('plan_json', {})}")
    else:
        print(f"✗ Failed to get run details: {run_response.status_code}")
        return
    
    if steps_response.status_code == 200:
        steps_data = steps_response.json()
        print(f"✓ Steps retrieved: {len(steps_data)} steps found")
        for i, step in enumerate(steps_data):
            print(f"  Step {i+1}: {step['step_key']} ({step['step_type']}) - {step['status']}")
    else:
        print(f"✗ Failed to get steps: {steps_response.status_code}")


async def main():
    """Main execution flow."""
    print("=" * 70)
    print(" PHASE 3 API TESTING SCRIPT")
    print("=" * 70)
    
    try:
        # A) CREATE RUN
        print("\nA) CREATE RUN")
        print("-" * 40)
        token = await login()
        if not token:
            print("✗ Authentication failed, cannot continue.")
            return
        
        run_id = await create_research_run(token)
        if not run_id:
            print("✗ Run creation failed, cannot continue.")
            return
        
        # B) BUILD BUNDLE
        print("\nB) BUILD BUNDLE")
        print("-" * 40)
        bundle = build_run_bundle(run_id)
        
        # C) SAVE BUNDLE
        print("\nC) SAVE BUNDLE")
        print("-" * 40)
        bundle_path = "C:\\ATS\\bundle.json"
        save_bundle_to_disk(bundle, bundle_path)
        
        # D) UPLOAD BUNDLE
        print("\nD) UPLOAD BUNDLE")
        print("-" * 40)
        upload_success = await upload_bundle(token, run_id, bundle)
        
        # E) VERIFY
        print("\nE) VERIFY")
        print("-" * 40)
        await verify_run_status(token, run_id)
        
        if upload_success:
            print("\n✅ ALL TESTS PASSED!")
            print(f"Final bundle.json saved at: {bundle_path}")
        else:
            print("\n❌ UPLOAD FAILED!")
            
    except Exception as e:
        print(f"\n💥 EXCEPTION: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
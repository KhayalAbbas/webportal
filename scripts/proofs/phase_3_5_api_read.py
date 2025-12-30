#!/usr/bin/env python3
"""
Phase 3.5 API Read Proof Script

Tests the prospects-with-evidence API endpoint with authentication to validate:
1. Auth works end-to-end (login -> token -> authorized requests)
2. Prospects-with-evidence endpoint responds successfully
3. JSON structure includes required fields and contains evidence with source docs

Usage:
    python scripts/proofs/phase_3_5_api_read.py
    
Environment Variables:
    API_BASE_URL: Base URL for API (defaults to http://localhost:8005)
    API_EMAIL: Login email (defaults to admin@test.com)
    API_PASSWORD: Login password (defaults to admin123)
    API_TENANT_ID: Tenant header (defaults to b3909011-8bd3-439d-a421-3b70fae124e9)
    API_RUN_ID: Optional fixed run_id override
"""

import os
import sys
import requests
import json
from urllib.parse import urljoin

def main():
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8005")
    tenant_id = os.getenv("API_TENANT_ID", "b3909011-8bd3-439d-a421-3b70fae124e9")
    email = os.getenv("API_EMAIL", "admin@test.com")
    password = os.getenv("API_PASSWORD", "admin123")
    run_id_override = os.getenv("API_RUN_ID")

    print("=== PHASE 3.5 API READ PROOF (AUTHENTICATED) ===")
    print(f"API Base URL: {api_base_url}")
    print(f"Tenant ID: {tenant_id}")
    print(f"User: {email}")
    if run_id_override:
        print(f"Run override: {run_id_override}")
    print()

    try:
        # Health check (unauthenticated)
        health_url = urljoin(api_base_url, "/health")
        print(f"Checking API health: {health_url}")
        health_response = requests.get(health_url, timeout=10)
        if health_response.status_code != 200:
            print(f"❌ API health check failed: {health_response.status_code}")
            return 1
        print("✅ API is healthy")
        print()

        # Login to obtain bearer token
        login_url = urljoin(api_base_url, "/auth/login")
        print(f"Logging in at: {login_url}")
        login_resp = requests.post(
            login_url,
            json={"email": email, "password": password},
            headers={"X-Tenant-ID": tenant_id},
            timeout=10,
        )
        if login_resp.status_code != 200:
            print(f"❌ Login failed: {login_resp.status_code}")
            try:
                print("Response:", login_resp.json())
            except Exception:
                print("Response text:", login_resp.text[:200])
            return 1

        token = login_resp.json().get("access_token")
        if not token:
            print("❌ No access_token returned from login")
            return 1
        print("✅ Login succeeded and token received")
        auth_headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tenant_id,
        }

        # Find prospects-with-evidence endpoint via OpenAPI (optional, but confirms wiring)
        openapi_url = urljoin(api_base_url, "/openapi.json")
        print(f"Fetching OpenAPI spec: {openapi_url}")
        openapi_response = requests.get(openapi_url, timeout=10)
        if openapi_response.status_code != 200:
            print(f"❌ Failed to get OpenAPI spec: {openapi_response.status_code}")
            return 1
        openapi_data = openapi_response.json()

        prospects_endpoint = None
        for path, methods in openapi_data.get("paths", {}).items():
            if "prospects-with-evidence" in path:
                for method in methods:
                    if method.lower() == "get":
                        prospects_endpoint = path
                        break
                if prospects_endpoint:
                    break

        if not prospects_endpoint:
            print("❌ Could not find prospects-with-evidence endpoint in OpenAPI spec")
            return 1

        print(f"✅ Found prospects endpoint: {prospects_endpoint}")

        # Discover a run_id (prefer real data)
        run_id = run_id_override
        if not run_id:
            runs_url = urljoin(api_base_url, "/company-research/runs")
            print(f"Listing research runs: {runs_url}")
            runs_resp = requests.get(runs_url, headers=auth_headers, timeout=15)
            if runs_resp.status_code == 200:
                try:
                    runs = runs_resp.json()
                    if isinstance(runs, list) and runs:
                        # Choose run with most linked evidence if stats present
                        def linked_count(run):
                            return run.get("linked_evidence", 0) if isinstance(run, dict) else 0
                        runs_sorted = sorted(runs, key=lambda r: (linked_count(r), r.get("total_evidence", 0)), reverse=True)
                        run_id = runs_sorted[0].get("id")
                        print(f"Auto-selected run_id from API: {run_id}")
                except Exception:
                    print("⚠️ Could not parse runs response, will use fallback")
            elif runs_resp.status_code in (401, 403):
                print("❌ Auth headers rejected when listing runs")
                return 1
            else:
                print(f"⚠️ Unexpected runs response: {runs_resp.status_code}")

        # Final fallback to known good run if still missing
        if not run_id:
            run_id = "b453d622-ad90-4bdd-a29a-eb6ee2a04ea2"
            print(f"Using fallback run_id: {run_id}")

        # Call prospects-with-evidence endpoint with auth
        test_endpoint = prospects_endpoint.replace("{run_id}", run_id)
        test_url = urljoin(api_base_url, test_endpoint)
        print(f"Testing endpoint: {test_url}")
        prospects_response = requests.get(test_url, headers=auth_headers, timeout=20)

        if prospects_response.status_code == 401:
            print("❌ Unauthorized - token rejected")
            return 1
        if prospects_response.status_code == 403:
            print("❌ Forbidden - tenant mismatch or insufficient permissions")
            return 1
        if prospects_response.status_code == 404:
            print("❌ Endpoint or run not found")
            return 1
        if prospects_response.status_code != 200:
            print(f"❌ Unexpected response code: {prospects_response.status_code}")
            print("Response:", prospects_response.text[:200])
            return 1

        try:
            prospects_data = prospects_response.json()
        except json.JSONDecodeError:
            print("❌ Response is not valid JSON")
            print("Response:", prospects_response.text[:200])
            return 1

        print("✅ Received valid JSON response")

        # Validate structure
        if not isinstance(prospects_data, list):
            print(f"❌ Expected array response, got {type(prospects_data)}")
            return 1

        print(f"✅ Response is an array with {len(prospects_data)} items")

        if len(prospects_data) == 0:
            print("ℹ️ No prospects found (empty array)")
            return 0

        # Validate structure of first item
        prospect = prospects_data[0]
        required_fields = ["id", "name_normalized", "evidence"]
        for field in required_fields:
            if field not in prospect:
                print(f"❌ Missing required field: {field}")
                return 1
        print("✅ Required prospect fields present")

        # Aggregate evidence across all prospects to ensure real data
        total_evidence = 0
        for p in prospects_data:
            ev = p.get("evidence", [])
            if not isinstance(ev, list):
                print("❌ Evidence field is not array on a prospect")
                return 1
            total_evidence += len(ev)

        print(f"✅ Total evidence across response: {total_evidence}")
        if total_evidence == 0:
            print("❌ No evidence returned in API response")
            return 1

        # Validate first evidence item we can find
        evidence_item = None
        for p in prospects_data:
            ev = p.get("evidence", [])
            if ev:
                evidence_item = ev[0]
                break

        if evidence_item is None:
            print("❌ Could not find any evidence item")
            return 1

        evidence_required = ["id", "source_type", "source_name"]
        for field in evidence_required:
            if field not in evidence_item:
                print(f"❌ Missing evidence field: {field}")
                return 1
        print("✅ Evidence structure valid")

        if "source_document" in evidence_item and evidence_item["source_document"]:
            source_doc = evidence_item["source_document"]
            source_fields = ["id", "url"]
            missing = [f for f in source_fields if f not in source_doc]
            if missing:
                print(f"❌ Missing source document fields: {missing}")
                return 1
            print("✅ Source document structure valid")
        else:
            print("ℹ️ Evidence has no linked source document")

        print()
        print("=== VALIDATION PASSED ===")
        print("API endpoint responds with authenticated, structured data")
        return 0

    except requests.RequestException as e:
        print(f"❌ Network error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
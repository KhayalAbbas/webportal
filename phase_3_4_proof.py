#!/usr/bin/env python3
"""
Phase 3.4 End-to-End Proof: Valid proposal mapping + job status semantics
"""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import Settings
import psycopg2
from uuid import uuid4

settings = Settings()
db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

def execute_sql(query, params=None):
    """Execute a SQL query and return results."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        if query.strip().upper().startswith('SELECT'):
            results = cur.fetchall()
            return results
        else:
            conn.commit()
            return None
    finally:
        conn.close()

def main():
    print("PHASE 3.4 PROOF: Valid Proposal Mapping + Job Status Semantics")
    print("=" * 70)
    
    # Clear old test data
    tenant_id = "11111111-1111-1111-1111-111111111111"
    print("Clearing old test data...")
    execute_sql("DELETE FROM research_jobs WHERE tenant_id = %s", (tenant_id,))
    execute_sql("DELETE FROM research_run_bundles WHERE tenant_id = %s", (tenant_id,))
    execute_sql("DELETE FROM research_runs WHERE tenant_id = %s", (tenant_id,))
    execute_sql("DELETE FROM company_research_runs WHERE tenant_id = %s", (tenant_id,))
    
    # Test 1: Compliant bundle workflow
    print("\n1. COMPLIANT BUNDLE WORKFLOW")
    print("-" * 40)
    
    run_id = str(uuid4())
    company_research_run_id = str(uuid4())
    
    # Get first available role ID
    role_id = execute_sql("SELECT id FROM role LIMIT 1")[0][0]
    
    # Create Phase 2 company research run
    execute_sql(
        "INSERT INTO company_research_runs (id, tenant_id, role_mandate_id, name, status, sector) VALUES (%s, %s, %s, %s, %s, %s)",
        (company_research_run_id, tenant_id, role_id, "Phase 3.4 Test", "completed", "Technology")
    )
    
    # Create Phase 3 research run linked to Phase 2
    execute_sql(
        "INSERT INTO research_runs (id, tenant_id, status, objective, constraints, rank_spec, bundle_sha256, company_research_run_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (run_id, tenant_id, "needs_review", "Test compliant bundle", "{}", "{}", "compliant_sha256", company_research_run_id)
    )
    
    # Create compliant bundle with all required fields
    compliant_bundle_json = {
        "version": "run_bundle_v1",
        "run_id": run_id,
        "plan_json": {
            "objective": "Find technology companies in renewable energy sector",
            "approach": "research_approach"
        },
        "steps": [],
        "sources": [
            {
                "sha256": "abc123def456",
                "url": "https://example.com/source1",
                "title": "Renewable Energy Report 2024",
                "content_text": "Sample content about renewable energy companies...",
                "retrieved_at": "2024-01-01T12:00:00Z",
                "mime_type": "text/html",
                "temp_id": "source_1"
            }
        ],
        "proposal_json": {
            "companies": [
                {
                    "name": "GreenTech Solutions Inc",
                    "domain": "greentech.example.com",
                    "evidence_snippets": [
                        "GreenTech Solutions is a leading provider of solar panel technology",
                        "The company has raised $50M in Series B funding for renewable energy projects"
                    ],
                    "source_sha256s": ["abc123def456"],
                    "metrics": [
                        {
                            "key": "funding_stage",
                            "type": "text",
                            "value": "Series B",
                            "source_temp_id": "source_1",
                            "evidence_snippet": "Series B funding announcement"
                        },
                        {
                            "key": "employee_count",
                            "type": "number",
                            "value": 150,
                            "unit": "employees"
                        }
                    ],
                    "sector": "Renewable Energy",
                    "description": "Solar panel technology provider"
                }
            ]
        }
    }
    
    # Store compliant bundle
    execute_sql(
        "INSERT INTO research_run_bundles (id, tenant_id, run_id, bundle_sha256, bundle_json) VALUES (%s, %s, %s, %s, %s)",
        (str(uuid4()), tenant_id, run_id, "compliant_sha256", json.dumps(compliant_bundle_json))
    )
    
    # Create job
    job_id = str(uuid4())
    execute_sql(
        "INSERT INTO research_jobs (id, tenant_id, run_id, job_type, status, payload_json, max_attempts, attempts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (job_id, tenant_id, run_id, "ingest_bundle", "queued", json.dumps({"bundle_sha256": "compliant_sha256"}), 3, 0)
    )
    
    # Update run status
    execute_sql("UPDATE research_runs SET status = %s WHERE id = %s", ("ingesting", run_id))
    
    print(f"Created compliant bundle run: {run_id}")
    print(f"Created job: {job_id}")
    
    # Test 2: Invalid bundle rejection
    print("\n2. INVALID BUNDLE TEST")
    print("-" * 40)
    
    invalid_run_id = str(uuid4())
    
    # Create invalid bundle - missing evidence_snippets
    invalid_bundle_json = {
        "version": "run_bundle_v1", 
        "run_id": invalid_run_id,
        "plan_json": {"approach": "test"},
        "steps": [],
        "sources": [],
        "proposal_json": {
            "companies": [
                {
                    "name": "Invalid Company",
                    "domain": "invalid.com",
                    "evidence_snippets": [],  # INVALID: empty
                    "source_sha256s": [],     # INVALID: empty
                    "metrics": {}             # INVALID: should be list
                }
            ]
        }
    }
    
    # Show what validation errors this should produce
    print(f"Invalid bundle created for testing: {invalid_run_id}")
    print("Expected validation errors:")
    print("- Company missing evidence_snippets (min 1)")
    print("- Company missing source_sha256s (min 1)")
    print("- No query found in plan_json.objective or proposal_json.query")
    
    # Show counts
    runs_count = execute_sql("SELECT COUNT(*) FROM research_runs WHERE tenant_id = %s", (tenant_id,))[0][0]
    jobs_count = execute_sql("SELECT COUNT(*) FROM research_jobs WHERE tenant_id = %s", (tenant_id,))[0][0]
    bundles_count = execute_sql("SELECT COUNT(*) FROM research_run_bundles WHERE tenant_id = %s", (tenant_id,))[0][0]
    company_runs_count = execute_sql("SELECT COUNT(*) FROM company_research_runs WHERE tenant_id = %s", (tenant_id,))[0][0]
    prospects_before = execute_sql("SELECT COUNT(*) FROM company_prospects WHERE tenant_id = %s", (tenant_id,))[0][0]
    
    print(f"\nCURRENT STATE:")
    print(f"  research_runs: {runs_count}")
    print(f"  company_research_runs: {company_runs_count}")
    print(f"  research_jobs: {jobs_count}")
    print(f"  research_run_bundles: {bundles_count}")
    print(f"  company_prospects (before): {prospects_before}")
    
    print(f"\n3. READY FOR WORKER PROCESSING")
    print("-" * 40)
    print("Execute: C:/ATS/.venv/Scripts/python.exe run_worker_once.py")
    
    print(f"\n4. VERIFICATION COMMANDS")
    print("-" * 40)
    print("After worker runs:")
    print(f"# Job status and retry info")
    print(f"SELECT status, attempts, retry_at, last_error FROM research_jobs WHERE id = '{job_id}';")
    print(f"")
    print(f"# Run status") 
    print(f"SELECT status FROM research_runs WHERE id = '{run_id}';")
    print(f"")
    print(f"# Company prospects after ingestion")
    print(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id = '{tenant_id}';")
    print(f"")
    print(f"Expected outcomes:")
    print("- If transformer works: job succeeded, run submitted, prospects increased")
    print("- If transformer fails: job failed/queued with retry_at, run failed, prospects unchanged")

if __name__ == "__main__":
    main()
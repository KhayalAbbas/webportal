#!/usr/bin/env python3
"""
Final end-to-end proof script with correct bundle format.
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
    print("FINAL END-TO-END PROOF")
    print("=" * 50)
    
    # Clear old test data
    print("Clearing old test data...")
    execute_sql("DELETE FROM research_jobs WHERE job_type = %s", ("ingest_bundle",))
    execute_sql("DELETE FROM research_run_bundles WHERE tenant_id = %s", ("11111111-1111-1111-1111-111111111111",))
    execute_sql("DELETE FROM research_runs WHERE tenant_id = %s", ("11111111-1111-1111-1111-111111111111",))
    
    tenant_id = "11111111-1111-1111-1111-111111111111"
    run_id = str(uuid4())
    
    # Show before counts
    runs_before = execute_sql("SELECT COUNT(*) FROM research_runs")[0][0]
    prospects_before = execute_sql("SELECT COUNT(*) FROM company_prospects WHERE tenant_id = %s", (tenant_id,))[0][0]
    jobs_before = execute_sql("SELECT COUNT(*) FROM research_jobs")[0][0]
    bundles_before = execute_sql("SELECT COUNT(*) FROM research_run_bundles")[0][0]
    
    print(f"\nBEFORE COUNTS:")
    print(f"  research_runs: {runs_before}")
    print(f"  company_prospects (tenant): {prospects_before}")
    print(f"  research_jobs: {jobs_before}")
    print(f"  research_run_bundles: {bundles_before}")
    
    # Create run
    print(f"\n1. CREATE RESEARCH RUN: {run_id}")
    execute_sql(
        "INSERT INTO research_runs (id, tenant_id, status, objective, constraints, rank_spec, bundle_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (run_id, tenant_id, "needs_review", "Test pipeline integration", "{}", "{}", "test_sha256")
    )
    
    # Create bundle with correct schema
    bundle_json = {
        "version": "run_bundle_v1",
        "run_id": run_id,
        "plan_json": {"approach": "test_pipeline"},
        "steps": [],
        "sources": [],
        "proposal_json": {
            "companies": [
                {
                    "name": "Pipeline Integration Test Corp",
                    "domain": "pipelinetest.example.com",
                    "evidence_snippets": [],
                    "evidence_summary": "",
                    "source_sha256s": [],
                    "metrics": {}
                }
            ]
        }
    }
    
    execute_sql(
        "INSERT INTO research_run_bundles (id, tenant_id, run_id, bundle_sha256, bundle_json) VALUES (%s, %s, %s, %s, %s)",
        (str(uuid4()), tenant_id, run_id, "test_sha256", json.dumps(bundle_json))
    )
    print("2. UPLOADED BUNDLE")
    
    # Create job
    job_id = str(uuid4())
    execute_sql(
        "INSERT INTO research_jobs (id, tenant_id, run_id, job_type, status, payload_json, max_attempts, attempts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (job_id, tenant_id, run_id, "ingest_bundle", "queued", json.dumps({"bundle_sha256": "test_sha256"}), 3, 0)
    )
    
    # Update run status
    execute_sql("UPDATE research_runs SET status = %s WHERE id = %s", ("ingesting", run_id))
    print(f"3. CREATED JOB: {job_id}")
    print("4. SET RUN STATUS: ingesting")
    
    # Show after setup
    runs_after = execute_sql("SELECT COUNT(*) FROM research_runs")[0][0]
    jobs_after = execute_sql("SELECT COUNT(*) FROM research_jobs")[0][0]
    bundles_after = execute_sql("SELECT COUNT(*) FROM research_run_bundles")[0][0]
    
    print(f"\nAFTER SETUP:")
    print(f"  research_runs: {runs_before} -> {runs_after}")
    print(f"  research_jobs: {jobs_before} -> {jobs_after}")
    print(f"  research_run_bundles: {bundles_before} -> {bundles_after}")
    
    print(f"\n5. RUN WORKER")
    print("-" * 40)
    print("Execute: C:/ATS/.venv/Scripts/python.exe run_worker_once.py")
    print("")
    print("VERIFICATION COMMANDS AFTER WORKER:")
    print(f"Job: SELECT status, error FROM research_jobs WHERE id = '{job_id}';")
    print(f"Run: SELECT status FROM research_runs WHERE id = '{run_id}';")
    print(f"Prospects before: {prospects_before}")
    print(f"Prospects after: SELECT COUNT(*) FROM company_prospects WHERE tenant_id = '{tenant_id}';")

if __name__ == "__main__":
    main()
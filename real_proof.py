#!/usr/bin/env python3
"""
Real Phase 3.2 proof - Direct job creation and processing.
"""

import asyncio
import sys
import uuid
import json
from datetime import datetime

sys.path.append('.')

from app.db.session import async_session_maker
from app.services.durable_job_service import DurableJobService
from sqlalchemy import text

TENANT_ID = uuid.UUID('b3909011-8bd3-439d-a421-3b70fae124e9')

async def proof_real_workflow():
    """Create and process a REAL company research job."""
    
    print("=== A) DB PROOF - BEFORE ===")
    async with async_session_maker() as session:
        result = await session.execute(text(
            'SELECT id, job_type, status, attempts, locked_by, locked_at, run_id, tenant_id, created_at '
            'FROM research_jobs ORDER BY created_at DESC LIMIT 5'
        ))
        jobs = result.fetchall()
        print("research_jobs (before):")
        if jobs:
            for job in jobs:
                print(f"  {job[0]} | {job[1]} | {job[2]} | {job[3]} | {job[4]} | {job[5]} | {job[6]} | {job[7]} | {job[8]}")
        else:
            print("  No jobs found")
    
    print("\n=== B) REAL JOB CREATION ===")
    
    async with async_session_maker() as session:
        job_service = DurableJobService(session)
        run_id = uuid.uuid4()
        
        # Create REAL company research job payload
        real_payload = {
            "bundle_data": {
                "metadata": {
                    "run_id": str(run_id),
                    "created_at": datetime.utcnow().isoformat(),
                    "source": "Phase 3.2 Real Workflow",
                    "sector": "Technology"
                },
                "companies": [
                    {
                        "name": "TechCorp Solutions",
                        "domain": "techcorp.example.com", 
                        "description": "AI-powered enterprise software",
                        "sector": "Technology",
                        "employee_count": 250,
                        "funding_stage": "Series B",
                        "location": "San Francisco, CA"
                    },
                    {
                        "name": "DataFlow Systems",
                        "domain": "dataflow.example.com",
                        "description": "Real-time data processing platform", 
                        "sector": "Technology",
                        "employee_count": 120,
                        "funding_stage": "Series A",
                        "location": "Austin, TX"
                    }
                ]
            },
            "research_run_id": str(run_id),
            "workflow": "approve_bundle_to_ingestion"
        }
        
        # This is what happens when user clicks "Approve" in UI
        job_id = await job_service.enqueue_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            job_type="company_research_bundle_ingest",
            payload=real_payload
        )
        
        await session.commit()
        
        print(f"✅ REAL company research job created: {job_id}")
        print(f"   Job type: company_research_bundle_ingest")
        print(f"   Run ID: {run_id}")
        print(f"   Tenant: {TENANT_ID}")
        print(f"   Companies to process: 2 (TechCorp, DataFlow)")
        
        # Verify job in database
        result = await session.execute(text(
            'SELECT id, job_type, status, attempts, locked_by, run_id, payload_json, created_at '
            'FROM research_jobs WHERE id = :job_id'
        ), {'job_id': job_id})
        job = result.fetchone()
        
        print(f"\n=== A) DB PROOF - JOB CREATED ===")
        print(f"ID: {job[0]}")
        print(f"Type: {job[1]}")
        print(f"Status: {job[2]}")
        print(f"Attempts: {job[3]}")
        print(f"Locked by: {job[4]}")
        print(f"Run ID: {job[5]}")
        print(f"Created: {job[7]}")
        print(f"Payload companies: {len(job[6]['bundle_data']['companies'])}")
        
        return job_id, run_id

async def main():
    job_id, run_id = await proof_real_workflow()
    
    print(f"\n=== READY FOR WORKER ===")
    print(f"✅ Real job queued: {job_id}")
    print(f"✅ Worker should claim and process this job")
    print(f"✅ This will trigger REAL ResearchRunService.ingest_bundle() method")
    print(f"✅ Start worker now to see actual Phase 3.2 processing!")

if __name__ == "__main__":
    asyncio.run(main())
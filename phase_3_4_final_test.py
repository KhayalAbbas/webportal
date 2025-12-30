#!/usr/bin/env python3
"""
Phase 3.4 Final Test - Create working bundle
"""

import json
import asyncio
from uuid import uuid4
from app.db.session import get_async_session_context
from app.models.research_run import ResearchRun
from app.models.research_run_bundle import ResearchRunBundle
from app.models.research_job import ResearchJob

async def create_compliant_bundle():
    """Create a bundle that should pass all validation"""
    
    tenant_id = "11111111-1111-1111-1111-111111111111"
    run_id = uuid4()
    
    # Create a fully compliant bundle
    bundle_data = {
        "company_name": "SuccessCorp Ltd",
        "sources": [{
            "name": "annual_report.pdf",
            "sha256": "d" * 64,  # Valid 64-char hex
            "content": "SuccessCorp Ltd is a SaaS company. Annual revenue: $75M. Founded 2018. CEO: Alice Johnson. Main product: Marketing automation platform for enterprises."
        }],
        "query": "What is SuccessCorp's business model and revenue?"
    }
    
    bundle_sha256 = "success_bundle_sha256"
    
    async with get_async_session_context() as session:
        # Create research run
        research_run = ResearchRun(
            id=run_id,
            tenant_id=tenant_id,
            status="pending",
            objective="Analyze SuccessCorp's business model and revenue",
            bundle_sha256=bundle_sha256
        )
        session.add(research_run)
        
        # Create bundle
        bundle = ResearchRunBundle(
            run_id=run_id,
            tenant_id=tenant_id,
            bundle_sha256=bundle_sha256,
            bundle_json=bundle_data
        )
        session.add(bundle)
        
        # Create job
        job = ResearchJob(
            run_id=run_id,
            tenant_id=tenant_id,
            job_type="ingest_bundle",
            status="queued",
            attempts=0,
            max_attempts=3,
            payload_json={"run_id": str(run_id), "tenant_id": str(tenant_id)}
        )
        session.add(job)
        
        await session.flush()
        
        print(f"✅ Created compliant bundle:")
        print(f"   Run ID: {run_id}")
        print(f"   Job ID: {job.id}")
        print(f"   Bundle SHA: {bundle_sha256}")
        print(f"   Company: {bundle_data['company_name']}")
        print(f"   Source SHA256 length: {len(bundle_data['sources'][0]['sha256'])}")

async def main():
    print("="*60)
    print(" PHASE 3.4 FINAL TEST: CREATING COMPLIANT BUNDLE")
    print("="*60)
    
    await create_compliant_bundle()
    
    print("\n" + "="*60)
    print(" READY FOR WORKER TEST")
    print("="*60)
    print("Run: python run_worker_once.py")
    print("Expected: Job should process successfully and create Phase 2 data")

if __name__ == "__main__":
    asyncio.run(main())
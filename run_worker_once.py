#!/usr/bin/env python3
"""Run worker once to process a single job."""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.worker import ResearchJobWorker

async def run_worker_once():
    worker = ResearchJobWorker()
    
    # Run one iteration
    from app.db.session import async_session_maker
    from app.services.durable_job_service import DurableJobService
    from app.services.research_run_service import ResearchRunService
    
    async with async_session_maker() as db:
        job_service = DurableJobService(db)
        research_service = ResearchRunService(db)
        
        # Try to claim a job
        job = await job_service.claim_next_job(worker.worker_id)
        
        if job:
            print(f"Claimed job: {job.id}")
            # Process the job
            success = await worker.process_job(job, job_service, research_service)
            
            # Commit the transaction
            await db.commit()
            
            if success:
                print(f"✅ Job {job.id} processed successfully")
            else:
                print(f"❌ Job {job.id} failed processing")
        else:
            print("No jobs available")

if __name__ == "__main__":
    asyncio.run(run_worker_once())
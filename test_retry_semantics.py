from app.db.session import async_session_maker
from app.models.research_job import ResearchJob
from sqlalchemy import text
import asyncio
from uuid import uuid4
from datetime import datetime, timedelta

async def test_retry_semantics():
    """Test retry semantics with a failing job"""
    print("=== RETRY SEMANTICS TEST ===")
    
    tenant_id = "33333333-3333-3333-3333-333333333333"
    run_id = uuid4()
    job_id = uuid4()
    
    async with async_session_maker() as session:
        # Create a job that will fail
        failing_job = ResearchJob(
            id=job_id,
            run_id=run_id,
            tenant_id=tenant_id,
            job_type="ingest_bundle",
            status="queued",
            attempts=0,
            max_attempts=3,
            payload_json={"run_id": str(run_id), "tenant_id": tenant_id}
        )
        session.add(failing_job)
        await session.commit()
        
        print(f"Created failing job: {job_id}")
        
        # Simulate retry progression
        from app.services.durable_job_service import DurableJobService
        job_service = DurableJobService(session)
        
        # Show initial state
        result = await session.execute(text(f"""
            SELECT status,attempts,max_attempts,retry_at,last_error 
            FROM research_jobs WHERE id='{job_id}'
        """))
        row = result.fetchone()
        print(f"Initial state: status={row[0]}, attempts={row[1]}, max_attempts={row[2]}, retry_at={row[3]}")
        
        # Simulate first failure
        await job_service.mark_job_failed(job_id, "Simulated failure 1")
        result = await session.execute(text(f"""
            SELECT status,attempts,max_attempts,retry_at,last_error 
            FROM research_jobs WHERE id='{job_id}'
        """))
        row = result.fetchone()
        print(f"After attempt 1: status={row[0]}, attempts={row[1]}, retry_at={row[3]}, error={row[4][:50]}...")
        
        # Simulate second failure
        await job_service.mark_job_failed(job_id, "Simulated failure 2")
        result = await session.execute(text(f"""
            SELECT status,attempts,max_attempts,retry_at,last_error 
            FROM research_jobs WHERE id='{job_id}'
        """))
        row = result.fetchone()
        print(f"After attempt 2: status={row[0]}, attempts={row[1]}, retry_at={row[3]}, error={row[4][:50]}...")
        
        # Simulate third failure (should be permanent)
        await job_service.mark_job_failed(job_id, "Simulated failure 3")
        result = await session.execute(text(f"""
            SELECT status,attempts,max_attempts,retry_at,last_error 
            FROM research_jobs WHERE id='{job_id}'
        """))
        row = result.fetchone()
        print(f"After attempt 3: status={row[0]}, attempts={row[1]}, retry_at={row[3]}, error={row[4][:50]}...")
        
        # Check final state
        if row[0] == "failed" and row[1] >= row[2]:
            print("✅ Job correctly marked as permanently failed")
        else:
            print(f"❌ Job state incorrect: status={row[0]}, attempts={row[1]}")

if __name__ == "__main__":
    asyncio.run(test_retry_semantics())
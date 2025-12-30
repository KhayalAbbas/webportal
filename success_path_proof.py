from app.db.session import async_session_maker
from app.models.company_research import CompanyResearchRun
from app.models.research_run import ResearchRun
from app.models.research_run_bundle import ResearchRunBundle
from app.models.research_job import ResearchJob
from app.services.research_run_service import ResearchRunService
from sqlalchemy import text
import asyncio
import json
from uuid import uuid4
from datetime import datetime

TENANT_ID = "22222222-2222-2222-2222-222222222222"
RUN_ID = uuid4()

async def success_path_proof():
    print("=== SUCCESS PATH PROOF ===")
    print(f"TENANT_ID: {TENANT_ID}")
    print(f"RUN_ID: {RUN_ID}")
    
    async with async_session_maker() as session:
        # A) Before counts
        result = await session.execute(text(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id='{TENANT_ID}'"))
        before_count = result.scalar()
        print(f"A) Before company_prospects count: {before_count}")
        
        # B) Create CompanyResearchRun and ResearchRun
        company_run = CompanyResearchRun(
            id=uuid4(),
            tenant_id=TENANT_ID,
            company_id=uuid4(),
            status="pending"
        )
        session.add(company_run)
        
        research_run = ResearchRun(
            id=RUN_ID,
            tenant_id=TENANT_ID,
            company_research_run_id=company_run.id,
            status="pending",
            objective="Test success path",
            bundle_sha256="test_success_sha256"
        )
        session.add(research_run)
        await session.commit()
        print(f"B) Created CompanyResearchRun: {company_run.id}")
        print(f"B) Created ResearchRun: {RUN_ID}")
        
        # C) Create valid bundle data
        valid_bundle = {
            "version": "run_bundle_v1",
            "run_id": str(RUN_ID),
            "plan_json": {"company": "TestCorp"},
            "steps": [{
                "step_key": "upload",
                "step_type": "validate", 
                "status": "ok",
                "inputs_json": {},
                "outputs_json": {},
                "provider_meta": {}
            }],
            "sources": [{
                "sha256": "b" * 64,
                "url": "uploaded://test.pdf",
                "retrieved_at": datetime.utcnow().isoformat(),
                "mime_type": "application/pdf",
                "title": "Test Document",
                "content_text": "TestCorp revenue is $50M annually. Founded 2019.",
                "meta": {"provider": "upload"},
                "temp_id": "source_1"
            }],
            "proposal_json": {
                "query": "What is TestCorp's revenue?",
                "sources": [{
                    "temp_id": "source_1",
                    "title": "Test Document",
                    "url": "uploaded://test.pdf",
                    "provider": "upload",
                    "fetched_at": datetime.utcnow().isoformat()
                }],
                "companies": [{
                    "name": "TestCorp",
                    "metrics": [{
                        "key": "annual_revenue",
                        "type": "currency",
                        "value": 50000000,
                        "source_temp_id": "source_1",
                        "evidence_snippet": "TestCorp revenue is $50M annually"
                    }],
                    "evidence_snippets": ["TestCorp revenue is $50M annually. Founded 2019."],
                    "source_sha256s": ["b" * 64]
                }],
                "evidence_requirements": [{
                    "key": "annual_revenue",
                    "description": "Annual revenue in USD",
                    "required": True,
                    "source_requirements": ["financial_document"]
                }]
            }
        }
        
        # Store bundle
        bundle = ResearchRunBundle(
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            bundle_sha256="test_success_sha256",
            bundle_json=valid_bundle
        )
        session.add(bundle)
        await session.commit()
        print(f"C) Valid bundle uploaded with proposal_json")
        
        # D) Check status after upload
        result = await session.execute(text(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}'"))
        run_status = result.fetchone()
        print(f"D) Research run status: id={run_status[0]}, status={run_status[1]}")
        
        result = await session.execute(text(f"SELECT COUNT(*) FROM research_run_bundles WHERE run_id='{RUN_ID}'"))
        bundle_count = result.scalar()
        print(f"D) Bundle count: {bundle_count}")
        
        # E) Approve (simulate approval)
        await session.execute(text(f"UPDATE research_runs SET status='ingesting' WHERE id='{RUN_ID}'"))
        
        # Create job
        job = ResearchJob(
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            job_type="ingest_bundle",
            status="queued",
            attempts=0,
            max_attempts=3,
            payload_json={"run_id": str(RUN_ID), "tenant_id": TENANT_ID}
        )
        session.add(job)
        await session.commit()
        
        result = await session.execute(text(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}'"))
        run_status = result.fetchone()
        print(f"E) After approval - run status: id={run_status[0]}, status={run_status[1]}")
        
        result = await session.execute(text(f"""
            SELECT id,job_type,status,attempts,max_attempts,retry_at,locked_by,locked_at,last_error
            FROM research_jobs WHERE run_id='{RUN_ID}' ORDER BY created_at DESC LIMIT 1
        """))
        job_row = result.fetchone()
        print(f"E) Job: id={job_row[0]}, type={job_row[1]}, status={job_row[2]}, attempts={job_row[3]}, max_attempts={job_row[4]}, retry_at={job_row[5]}")
        
        return job.id

if __name__ == "__main__":
    job_id = asyncio.run(success_path_proof())
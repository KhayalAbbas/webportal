from app.db.session import async_session_maker
from app.models.research_run import ResearchRun
from app.models.research_run_bundle import ResearchRunBundle
from app.models.research_job import ResearchJob
from sqlalchemy import text
import asyncio
import json
from uuid import UUID
from datetime import datetime

TENANT_ID = "44444444-4444-4444-4444-444444444444"
RUN_ID = "55555555-5555-5555-5555-555555555555"

async def simple_success_test():
    async with async_session_maker() as session:
        # A) Before counts
        result = await session.execute(text(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id='{TENANT_ID}'"))
        print(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id='{TENANT_ID}';")
        print(f"{result.scalar()}")
        
        # B) Create ResearchRun only
        research_run = ResearchRun(
            id=UUID(RUN_ID),
            tenant_id=TENANT_ID,
            status="needs_review",
            objective="Test success path proof",
            bundle_sha256="success_test_sha256"
        )
        session.add(research_run)
        await session.commit()
        
        # C) Upload VALID RunBundleV1
        valid_bundle = {
            "version": "run_bundle_v1",
            "run_id": RUN_ID,
            "plan_json": {"company": "TestCorp"},
            "steps": [{
                "step_key": "extract",
                "step_type": "extract",
                "status": "ok",
                "inputs_json": {},
                "outputs_json": {},
                "provider_meta": {}
            }],
            "sources": [{
                "sha256": "c" * 64,
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
                    "source_sha256s": ["c" * 64]
                }],
                "evidence_requirements": [{
                    "key": "annual_revenue",
                    "description": "Annual revenue in USD",
                    "required": True,
                    "source_requirements": ["financial_document"]
                }]
            }
        }
        
        bundle = ResearchRunBundle(
            run_id=UUID(RUN_ID),
            tenant_id=TENANT_ID,
            bundle_sha256="success_test_sha256",
            bundle_json=valid_bundle
        )
        session.add(bundle)
        await session.commit()
        
        # D) After upload
        result = await session.execute(text(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}'"))
        row = result.fetchone()
        print(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}';")
        print(f"{row[0]} | {row[1]}")
        
        result = await session.execute(text(f"SELECT COUNT(*) FROM research_run_bundles WHERE run_id='{RUN_ID}'"))
        count = result.scalar()
        print(f"SELECT COUNT(*) FROM research_run_bundles WHERE run_id='{RUN_ID}';")
        print(f"{count}")
        
        # E) Approve
        await session.execute(text(f"UPDATE research_runs SET status='ingesting' WHERE id='{RUN_ID}'"))
        
        job = ResearchJob(
            run_id=UUID(RUN_ID),
            tenant_id=TENANT_ID,
            job_type="ingest_bundle",
            status="queued",
            attempts=0,
            max_attempts=3,
            payload_json={"run_id": RUN_ID, "tenant_id": TENANT_ID}
        )
        session.add(job)
        await session.commit()
        
        result = await session.execute(text(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}'"))
        row = result.fetchone()
        print(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}';")
        print(f"{row[0]} | {row[1]}")
        
        result = await session.execute(text(f"SELECT id,job_type,status,attempts,max_attempts,retry_at,locked_by,locked_at,last_error FROM research_jobs WHERE run_id='{RUN_ID}' ORDER BY created_at DESC LIMIT 1"))
        row = result.fetchone()
        print(f"SELECT id,job_type,status,attempts,max_attempts,retry_at,locked_by,locked_at,last_error FROM research_jobs WHERE run_id='{RUN_ID}' ORDER BY created_at DESC LIMIT 1;")
        print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} | {row[8]}")

if __name__ == "__main__":
    asyncio.run(simple_success_test())
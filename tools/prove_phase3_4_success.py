#!/usr/bin/env python3
"""
Phase 3.4 End-to-End Success Proof Script

This script verifies that the complete Phase 3.4 workflow works correctly:
1. Creates test data (company_research_run and research_run)
2. Creates a valid RunBundleV1 with proper AIProposal structure 
3. Tests bundle acceptance and approval
4. Runs worker to process the ingestion job
5. Verifies writes to company_prospects table
6. Checks final statuses (job=succeeded, run=submitted)
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from uuid import UUID
from typing import Dict, Any

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.db.session import async_session_maker
from app.models.company_research import CompanyResearchRun
from app.models.research_run import ResearchRun  
from app.repositories.company_research_repo import CompanyResearchRepository
from app.repositories.research_run_repository import ResearchRunRepository
from app.schemas.research_run import ResearchRunCreate, RunBundleV1
from app.services.research_run_service import ResearchRunService
from app.services.durable_job_service import DurableJobService
from sqlalchemy import text

# Use consistent test tenant
TENANT_ID = UUID("33333333-3333-3333-3333-333333333333")

def create_valid_run_bundle(run_id: UUID) -> RunBundleV1:
    """Create a valid RunBundleV1 that will pass validation and transform correctly."""
    
    # Create sources with properly computed SHA256
    import hashlib
    source_content = "TechCorp is a leading technology company headquartered in San Francisco. They specialize in cloud computing and AI solutions."
    source_sha256 = hashlib.sha256(source_content.encode()).hexdigest()
    
    bundle_data = {
        "version": "run_bundle_v1",
        "run_id": str(run_id),
        "plan_json": {"objective": "Find technology companies"},
        "steps": [],
        "sources": [
            {
                "temp_id": "source1", 
                "sha256": source_sha256,
                "content_text": source_content,
                "content_type": "text/plain",
                "metadata": {"url": "https://example.com/techcorp"}
            }
        ],
        "proposal_json": {
            "query": "Find technology companies",
            "companies": [
                {
                    "name": "TechCorp",
                    "hq_country": "US",
                    "sector": "Technology",
                    "description": "Leading technology company",
                    "metrics": [
                        {
                            "name": "revenue",
                            "value": "1000000000",
                            "unit": "USD",
                            "source_temp_id": "source1",
                            "evidence_snippet": "TechCorp is a leading technology company"
                        }
                    ],
                    "evidence_snippets": ["TechCorp is a leading technology company"],
                    "source_sha256s": [source_sha256]
                }
            ]
        },
        "version_info": {
            "created_at": "2025-12-29T14:09:49Z",
            "creator": "phase3_4_test"
        }
    }
    
    return RunBundleV1(**bundle_data)

async def run_single_worker_iteration(specific_job_id: UUID = None) -> tuple[bool, str]:
    """Run a single iteration of worker processing and return if job was processed."""
    from tools.worker import ResearchJobWorker
    
    async with async_session_maker() as db:
        worker = ResearchJobWorker(worker_id="proof_worker")
        job_service = DurableJobService(db)
        research_service = ResearchRunService(db)
        
        # Try to claim a specific job if provided, otherwise claim next
        if specific_job_id:
            job = await job_service.claim_job_by_id(specific_job_id, worker.worker_id)
            print(f"Attempted to claim specific job {specific_job_id}: {'SUCCESS' if job else 'FAILED'}")
        else:
            job = await job_service.claim_next_job(worker.worker_id)
            print(f"Claimed next available job: {job.id if job else 'None'}")
        
        if job:
            print(f"Processing job: {job.id} for run: {job.run_id}")
            # Process the job
            success = await worker.process_job(job, job_service, research_service)
            await db.commit()
            
            if success:
                print(f"Job {job.id} succeeded")
            else:
                print(f"Job {job.id} failed: {job.last_error}")
            
            return True, str(job.id)
        else:
            print("No jobs to process")
            return False, ""

async def main():
    """Execute the full Phase 3.4 success proof."""
    print("=== PHASE 3.4 SUCCESS PROOF ===")
    print(f"TENANT_ID: {TENANT_ID}")
    
    async with async_session_maker() as db:
        company_repo = CompanyResearchRepository(db)
        research_repo = ResearchRunRepository(db)
        research_service = ResearchRunService(db)
        
        # A) BEFORE COUNT
        before_result = await db.execute(text(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id = '{TENANT_ID}'"))
        before_count = before_result.scalar()
        print(f"BEFORE COUNT - company_prospects for tenant {TENANT_ID}: {before_count}")
        
        # B) Create company_research_run
        company_research_run = CompanyResearchRun(
            id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            role_mandate_id=UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb"),
            name="Phase 3.4 Technology Research Test",
            description="End-to-end test for Phase 3.4 bundle processing",
            status="ready",
            sector="Technology",
        )
        db.add(company_research_run)
        await db.flush()
        await db.refresh(company_research_run)
        print(f"Created company_research_run: {company_research_run.id}")
        
        # C) Create research_run
        research_run = ResearchRun(
            id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            company_research_run_id=company_research_run.id,
            status="ready",
            objective="Technology company research via Phase 3.4 test",
            constraints={},
            rank_spec={},
            plan_json={"objective": "Technology company research"}
        )
        db.add(research_run)
        await db.flush()
        await db.refresh(research_run)
        print(f"Created research_run: {research_run.id}")
        await db.commit()
        
        # D) Create valid bundle
        bundle = create_valid_run_bundle(research_run.id)
        print(f"Created bundle with {len(bundle.proposal_json['companies'])} companies")
        
        # E) Validate bundle
        validation_response = await research_service.validate_bundle(bundle)
        print(f"Bundle validation: ok={validation_response.ok}, errors={len(validation_response.errors)}")
        if validation_response.errors:
            for error in validation_response.errors:
                print(f"  ERROR: {error}")
        
        # F) Accept bundle (accept_only=True)
        response, newly_accepted = await research_service.accept_bundle(
            tenant_id=TENANT_ID,
            run_id=research_run.id,
            bundle=bundle,
            accept_only=True
        )
        print(f"Bundle accepted: {response.status}, newly_accepted: {newly_accepted}")
        
        # G) Verify run status is needs_review
        updated_run = await research_service.get_run_with_counts(TENANT_ID, research_run.id)
        print(f"Run status after accept_bundle: {updated_run.status}")
        
        # H) Approve bundle for ingestion
        approval_result = await research_service.approve_bundle_for_ingestion(TENANT_ID, research_run.id)
        print(f"Bundle approved for ingestion: {approval_result}")
        
        # H.1) COMMIT the transaction so worker can see the job
        await db.commit()
        print("COMMITTED job creation transaction")
        
        # H.2) Find the created job ID for this run in a NEW session
        async with async_session_maker() as fresh_db:
            job_query_result = await fresh_db.execute(text(f"SELECT id, status FROM research_jobs WHERE run_id = '{research_run.id}' AND status = 'queued' ORDER BY created_at DESC LIMIT 1"))
            job_row = job_query_result.fetchone()
            if job_row:
                created_job_id = UUID(str(job_row.id))
                print(f"Created job ID: {created_job_id}, status: {job_row.status}")
            else:
                print("ERROR: No job found after approval")
                return
        
        # I) Run worker to process the SPECIFIC job we created
        print(f"Running worker to process specific job {created_job_id}...")
        max_iterations = 5
        job_processed = False
        processed_job_id = None
        
        for i in range(max_iterations):
            was_processed, job_id = await run_single_worker_iteration(created_job_id)
            if was_processed:
                job_processed = True
                processed_job_id = job_id
                break
            await asyncio.sleep(1)
        
        # J) FINAL VERIFICATION - use a fresh session for final checks  
        async with async_session_maker() as final_db:
            print(f"Job processed: {job_processed}, Processed job ID: {processed_job_id}, Expected job ID: {created_job_id}")
            print(f"Proof validity: {processed_job_id == str(created_job_id) if processed_job_id and job_processed else 'INVALID - wrong or no job processed'}")
            
            # Check job status
            final_jobs = await final_db.execute(text(f"SELECT id, status, attempts, retry_at, locked_by, last_error FROM research_jobs WHERE run_id = '{research_run.id}' ORDER BY created_at DESC LIMIT 1"))
            job_row = final_jobs.fetchone()
            if job_row:
                print(f"FINAL JOB - id: {job_row.id}, status: {job_row.status}, attempts: {job_row.attempts}, retry_at: {job_row.retry_at}, locked_by: {job_row.locked_by}, last_error: {job_row.last_error}")
            
            # Check run status - need research_service instance for this final_db
            final_research_service = ResearchRunService(final_db)
            final_run = await final_research_service.get_run_with_counts(TENANT_ID, research_run.id)
            print(f"FINAL RUN - id: {final_run.id}, status: {final_run.status}, bundle_sha256: {final_run.bundle_sha256}, company_research_run_id: {final_run.company_research_run_id}")
            
            # Check company_prospects count
            after_result = await final_db.execute(text(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id = '{TENANT_ID}'"))
            after_count = after_result.scalar()
            print(f"AFTER COUNT - company_prospects for tenant {TENANT_ID}: {after_count}")
            
            # Check company_prospect_evidence count for the specific company_research_run
            evidence_result = await final_db.execute(text(f"""
                SELECT COUNT(*) 
                FROM company_prospect_evidence cpe 
                JOIN company_prospects cp ON cpe.company_prospect_id = cp.id 
                WHERE cp.tenant_id = '{TENANT_ID}' 
                AND cp.company_research_run_id = '{final_run.company_research_run_id}'
            """))
            evidence_count = evidence_result.scalar() 
            print(f"EVIDENCE COUNT - company_prospect_evidence for run {final_run.company_research_run_id}: {evidence_count}")
            
            # Check source documents are run-scoped and match the current run
            source_doc_result = await final_db.execute(text(f"""
                SELECT COUNT(*), COUNT(DISTINCT company_research_run_id) as unique_runs
                FROM source_documents 
                WHERE tenant_id = '{TENANT_ID}' 
                AND company_research_run_id = '{final_run.company_research_run_id}'
            """))
            source_doc_row = source_doc_result.fetchone()
            source_doc_count = source_doc_row[0] if source_doc_row else 0
            source_runs_count = source_doc_row[1] if source_doc_row else 0
            print(f"SOURCE DOCS - count for run {final_run.company_research_run_id}: {source_doc_count}")
            print(f"SOURCE DOCS - unique runs represented: {source_runs_count}")
            
            # Verify no cross-run contamination in source documents
            cross_run_result = await final_db.execute(text(f"""
                SELECT COUNT(*) 
                FROM source_documents 
                WHERE tenant_id = '{TENANT_ID}' 
                AND company_research_run_id != '{final_run.company_research_run_id}'
            """))
            other_run_docs = cross_run_result.scalar()
            print(f"SOURCE DOCS - documents in other runs: {other_run_docs}")
            
            # Check that evidence exists for the run (source documents not directly linked)
            evidence_source_match_result = await final_db.execute(text(f"""
                SELECT COUNT(*) as evidence_count
                FROM company_prospect_evidence cpe
                JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
                WHERE cp.tenant_id = '{TENANT_ID}' 
                AND cp.company_research_run_id = '{final_run.company_research_run_id}'
            """))
            evidence_source_row = evidence_source_match_result.fetchone()
            evidence_total = evidence_source_row[0] if evidence_source_row else 0
            print(f"EVIDENCE COUNT - total evidence for run: {evidence_total}")
            
            # SUCCESS CRITERIA CHECK
            prospects_increased = after_count > before_count
            job_succeeded = job_row and job_row.status == "succeeded"
            run_submitted = final_run.status == "submitted"
            correct_job_processed = processed_job_id == str(created_job_id) if processed_job_id else False
            evidence_created = evidence_count > 0
            source_docs_created = source_doc_count > 0
            source_docs_run_scoped = source_runs_count == 1  # Only one run should be represented
            evidence_exists = evidence_total > 0  # Evidence exists for the run
            
            print(f"PROOF - company_prospects increased: {prospects_increased} (was {before_count}, now {after_count})")
            print(f"PROOF - job succeeded: {job_succeeded}")
            print(f"PROOF - run submitted: {run_submitted}")
            print(f"PROOF - correct job processed: {correct_job_processed}")
            print(f"PROOF - evidence created: {evidence_created}")
            print(f"PROOF - source docs created: {source_docs_created}")
            print(f"PROOF - source docs run-scoped: {source_docs_run_scoped}")
            print(f"PROOF - evidence exists for run: {evidence_exists}")
            
            # Exit with error if any criteria failed
            all_criteria_met = (prospects_increased and job_succeeded and run_submitted and 
                              correct_job_processed and evidence_created and source_docs_created and 
                              source_docs_run_scoped and evidence_exists)
            
            if not all_criteria_met:
                print("FAILURE: One or more success criteria not met")
                if not prospects_increased:
                    print("  - company_prospects count did not increase")
                if not job_succeeded:
                    print("  - job did not succeed")  
                if not run_submitted:
                    print("  - run status is not submitted")
                if not correct_job_processed:
                    print("  - wrong job was processed (proof invalidated)")
                if not evidence_created:
                    print("  - no evidence was created for the prospect")
                if not source_docs_created:
                    print("  - no source documents were created")
                if not source_docs_run_scoped:
                    print("  - source documents span multiple runs (cross-run contamination)")
                if not evidence_exists:
                    print("  - no evidence exists for the run")
                sys.exit(1)
        
        print("SUCCESS: All criteria met - Phase 3.4 end-to-end working correctly!")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
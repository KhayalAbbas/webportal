#!/usr/bin/env python3
"""
Durable job worker for research bundle processing.

This worker polls the research_jobs table for queued jobs and processes them
using the ResearchRunService. Implements proper locking, retry, and graceful shutdown.
"""

import asyncio
import logging
import os
import signal
import socket
import sys
import traceback

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.db.session import async_session_maker
from app.services.durable_job_service import DurableJobService  
from app.services.research_run_service import ResearchRunService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('worker.log')
    ]
)

logger = logging.getLogger(__name__)


class ResearchJobWorker:
    """Durable job worker for research bundle processing."""
    
    def __init__(self, worker_id: str = None, poll_interval: float = 5.0):
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.poll_interval = poll_interval
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        logger.info(f"Worker {self.worker_id} initialized")
    
    def setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT."""
        def signal_handler(signum, frame):
            logger.info(f"Worker {self.worker_id} received signal {signum}, shutting down gracefully...")
            self.shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    async def process_job(self, job, job_service: DurableJobService, research_service: ResearchRunService) -> bool:
        """
        Process a single job.
        
        Args:
            job: ResearchJob to process
            job_service: Job service for status updates
            research_service: Research service for business logic
            
        Returns:
            bool: True if successful, False if failed
        """
        try:
            logger.info(f"Processing job {job.id} (type: {job.job_type}, attempt: {job.attempts})")
            
            if job.job_type == "ingest_bundle":
                await self._process_bundle_ingestion(job, research_service)
            else:
                raise ValueError(f"Unknown job type: {job.job_type}")
            
            # Mark as succeeded
            await job_service.mark_job_succeeded(job.id)
            logger.info(f"Job {job.id} completed successfully")
            return True
            
        except Exception as e:
            error_msg = f"Job {job.id} failed: {str(e)}"
            logger.error(f"{error_msg}")
            logger.error(traceback.format_exc())
            
            # Mark as failed (service will handle retry logic)
            await job_service.mark_job_failed(job.id, error_msg)
            return False
    
    async def _process_bundle_ingestion(self, job, research_service: ResearchRunService):
        """Process a real bundle ingestion job."""
        payload = job.payload_json
        bundle_sha256 = payload.get("bundle_sha256")
        
        logger.info(f"Starting bundle ingestion for tenant {job.tenant_id}, run {job.run_id}")
        logger.info(f"Bundle SHA256: {bundle_sha256}")
        
        # Load the stored bundle from research_run_bundles
        bundle_data = await research_service._get_stored_bundle(job.tenant_id, job.run_id)
        if not bundle_data:
            raise ValueError(f"No stored bundle found for tenant {job.tenant_id}, run {job.run_id}")
        
        # Parse the bundle 
        from app.schemas.research_run import RunBundleV1
        bundle = RunBundleV1(**bundle_data.bundle_json)
        
        # Get companies from the proposal_json
        companies = bundle.proposal_json.get("companies", [])
        logger.info(f"Loaded bundle with {len(companies)} companies")
        
        # Execute the real Phase 2 ingestion pipeline
        logger.info("Calling Phase 2 ingestion pipeline...")
        result = await research_service._ingest_bundle_background(
            tenant_id=job.tenant_id,
            run_id=job.run_id,
            bundle=bundle
        )
        
        if result.get("success"):
            logger.info("Phase 2 ingestion completed successfully")
        else:
            raise ValueError(f"Phase 2 ingestion failed: {result}")
        
    async def poll_and_process(self):
        """Main worker loop - polls for jobs and processes them."""
        logger.info(f"Worker {self.worker_id} starting job polling (interval: {self.poll_interval}s)")
        
        while not self.shutdown_event.is_set():
            try:
                async with async_session_maker() as db:
                    job_service = DurableJobService(db)
                    research_service = ResearchRunService(db)
                    
                    # Try to claim a job
                    job = await job_service.claim_next_job(self.worker_id)
                    
                    if job:
                        # Process the job
                        success = await self.process_job(job, job_service, research_service)
                        
                        # Commit the transaction
                        await db.commit()
                        
                        if success:
                            logger.info(f"Job {job.id} processed successfully")
                        else:
                            logger.error(f"Job {job.id} failed processing")
                            
                        # Continue immediately to check for more jobs
                        continue
                    
                    else:
                        # No jobs available, wait before polling again
                        logger.debug(f"No jobs available, waiting {self.poll_interval}s")
                        
            except Exception as e:
                logger.error(f"Worker loop error: {str(e)}")
                logger.error(traceback.format_exc())
                
            # Wait before next poll (unless we processed a job successfully)
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=self.poll_interval)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling
        
        logger.info(f"Worker {self.worker_id} stopped")
    
    async def run(self):
        """Start the worker."""
        self.setup_signal_handlers()
        self.running = True
        
        try:
            await self.poll_and_process()
        except Exception as e:
            logger.error(f"Worker {self.worker_id} crashed: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.running = False
            logger.info(f"Worker {self.worker_id} shutting down")


async def main():
    """Main entry point."""
    worker = ResearchJobWorker()
    
    logger.info("=== Research Job Worker Starting ===")
    logger.info(f"Worker ID: {worker.worker_id}")
    logger.info(f"Poll interval: {worker.poll_interval}s")
    logger.info(f"Project root: {project_root}")
    
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
"""
Durable job service for persistent background processing using PostgreSQL.

Replaces the in-memory asyncio job queue with database-backed job storage
for durability across process restarts and multi-worker deployments.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from uuid import UUID

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_job import ResearchJob


logger = logging.getLogger(__name__)


class DurableJobService:
    """Service for managing durable background jobs."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def enqueue_job(
        self,
        tenant_id: UUID,
        run_id: UUID,
        job_type: str,
        payload: Dict[str, Any],
        max_attempts: int = 3,
    ) -> str:
        """
        Enqueue a job for background processing.
        
        Args:
            tenant_id: Tenant ID for isolation
            run_id: Research run ID that triggered this job
            job_type: Type identifier (e.g., "ingest_bundle")
            payload: Job payload data
            max_attempts: Maximum retry attempts
            
        Returns:
            str: Job ID
        """
        job_id = str(uuid.uuid4())
        
        job = ResearchJob(
            id=uuid.UUID(job_id),
            tenant_id=tenant_id,
            run_id=run_id,
            job_type=job_type,
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            payload_json=payload,
        )
        
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        
        logger.info(f"Job {job_id} enqueued for tenant {tenant_id}, run {run_id}, type {job_type}")
        return job_id
    
    async def get_job_status(self, job_id: str) -> Optional[ResearchJob]:
        """Get job by ID."""
        result = await self.db.execute(
            select(ResearchJob).where(ResearchJob.id == uuid.UUID(job_id))
        )
        return result.scalar_one_or_none()
    
    async def get_jobs_for_run(self, tenant_id: UUID, run_id: UUID) -> list[ResearchJob]:
        """Get all jobs for a specific run."""
        result = await self.db.execute(
            select(ResearchJob).where(
                and_(
                    ResearchJob.tenant_id == tenant_id,
                    ResearchJob.run_id == run_id
                )
            ).order_by(ResearchJob.created_at)
        )
        return list(result.scalars())
    
    async def claim_next_job(self, worker_id: str) -> Optional[ResearchJob]:
        """
        Claim the next available job for processing.
        
        Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
        
        Args:
            worker_id: Unique identifier for this worker process
            
        Returns:
            ResearchJob if claimed, None if no jobs available
        """
        # Find jobs that are either:
        # 1. Queued and ready for retry (retry_at is null or <= now)
        # 2. Locked but expired (stale locks from crashed workers)
        lock_timeout = timedelta(minutes=30)  # Consider locks stale after 30 minutes
        cutoff_time = datetime.utcnow() - lock_timeout
        now = datetime.utcnow()
        
        result = await self.db.execute(
            select(ResearchJob)
            .where(
                and_(
                    or_(
                        # Queued jobs ready for retry
                        and_(
                            ResearchJob.status == "queued",
                            or_(
                                ResearchJob.retry_at.is_(None),
                                ResearchJob.retry_at <= now
                            )
                        ),
                        # Stale locked jobs
                        and_(
                            ResearchJob.status == "running",
                            ResearchJob.locked_at < cutoff_time
                        )
                    )
                )
            )
            .order_by(ResearchJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        
        job = result.scalar_one_or_none()
        if job:
            # Claim the job
            job.status = "running"
            job.locked_at = datetime.utcnow()
            job.locked_by = worker_id
            job.attempts += 1
            
            await self.db.flush()
            logger.info(f"Worker {worker_id} claimed job {job.id} (attempt {job.attempts}/{job.max_attempts})")
            
        return job
    
    async def claim_job_by_id(self, job_id: UUID, worker_id: str) -> Optional[ResearchJob]:
        """
        Claim a specific job by ID for processing.
        
        Uses SELECT FOR UPDATE for safe transactional claiming.
        Only allows claiming if status='queued' AND (retry_at IS NULL OR retry_at <= now()).
        
        Args:
            job_id: Specific job ID to claim
            worker_id: Unique identifier for this worker process
            
        Returns:
            ResearchJob if claimed successfully, None if not claimable
        """
        now = datetime.utcnow()
        
        result = await self.db.execute(
            select(ResearchJob)
            .where(
                and_(
                    ResearchJob.id == job_id,
                    ResearchJob.status == "queued",
                    or_(
                        ResearchJob.retry_at.is_(None),
                        ResearchJob.retry_at <= now
                    )
                )
            )
            .with_for_update()
        )
        
        job = result.scalar_one_or_none()
        if job:
            # Claim the job
            job.status = "running"
            job.locked_at = datetime.utcnow()
            job.locked_by = worker_id
            job.attempts += 1
            job.updated_at = datetime.utcnow()
            
            await self.db.flush()
            logger.info(f"Worker {worker_id} claimed specific job {job_id} (attempt {job.attempts}/{job.max_attempts})")
            
        return job

    async def mark_job_succeeded(self, job_id: UUID, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark job as successfully completed."""
        job = await self.db.get(ResearchJob, job_id)
        if job:
            job.status = "succeeded"
            job.locked_at = None
            job.locked_by = None
            job.last_error = None
            if result:
                job.payload_json.update({"result": result})
            await self.db.flush()
            logger.info(f"Job {job_id} marked as succeeded")
    
    async def mark_job_failed(self, job_id: UUID, error: str) -> None:
        """Mark job as failed with error message and implement retry logic."""
        job = await self.db.get(ResearchJob, job_id)
        if job:
            job.last_error = error
            
            if job.attempts >= job.max_attempts:
                # Permanent failure
                job.status = "failed"
                job.locked_at = None
                job.locked_by = None
                job.retry_at = None
                logger.error(f"Job {job_id} permanently failed after {job.attempts} attempts: {error}")
            else:
                # Schedule retry with exponential backoff
                # Base delay: 30 seconds, then 60s, 120s, etc.
                base_delay_seconds = 30
                backoff_multiplier = 2
                delay_seconds = base_delay_seconds * (backoff_multiplier ** (job.attempts - 1))
                retry_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
                
                job.status = "queued"
                job.locked_at = None
                job.locked_by = None
                job.retry_at = retry_time
                
                logger.warning(f"Job {job_id} failed (attempt {job.attempts}/{job.max_attempts}), will retry in {delay_seconds}s at {retry_time}: {error}")
            
            await self.db.flush()
    
    async def cleanup_old_jobs(self, older_than: timedelta = timedelta(days=7)) -> int:
        """
        Clean up old completed jobs to prevent table bloat.
        
        Args:
            older_than: Remove completed jobs older than this duration
            
        Returns:
            Number of jobs cleaned up
        """
        cutoff_time = datetime.utcnow() - older_than
        
        result = await self.db.execute(
            select(ResearchJob.id).where(
                and_(
                    or_(
                        ResearchJob.status == "succeeded",
                        ResearchJob.status == "failed"
                    ),
                    ResearchJob.updated_at < cutoff_time
                )
            )
        )
        job_ids = [row[0] for row in result.fetchall()]
        
        if job_ids:
            for job_id in job_ids:
                job = await self.db.get(ResearchJob, job_id)
                if job:
                    await self.db.delete(job)
            
            await self.db.flush()
            logger.info(f"Cleaned up {len(job_ids)} old jobs")
        
        return len(job_ids)
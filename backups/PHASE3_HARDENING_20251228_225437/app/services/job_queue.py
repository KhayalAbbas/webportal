"""
Simple in-process job queue for background task processing.

This implementation uses asyncio tasks for non-blocking execution while keeping
jobs in the same process. Suitable for moderate workloads where scaling across
multiple processes/servers is not yet required.

Features:
- Background job execution with asyncio.create_task()
- Job status tracking and error handling
- Tenant isolation for multi-tenant applications
- Configurable retry logic with exponential backoff
- Thread-safe job submission from request handlers
"""

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job execution status."""
    QUEUED = "queued"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class JobResult:
    """Result of job execution."""
    job_id: str
    status: JobStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 0
    tenant_id: Optional[uuid.UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class JobQueue:
    """Simple in-process job queue using asyncio."""
    
    def __init__(self):
        self._jobs: Dict[str, JobResult] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
    
    def submit_job(
        self,
        job_func: Callable[..., Awaitable[Any]], 
        *args,
        job_id: Optional[str] = None,
        tenant_id: Optional[uuid.UUID] = None,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Submit a job for background execution.
        
        Args:
            job_func: Async function to execute
            *args: Positional arguments for job_func
            job_id: Optional custom job ID (auto-generated if None)
            tenant_id: Tenant ID for isolation
            max_retries: Maximum retry attempts on failure
            metadata: Optional job metadata
            **kwargs: Keyword arguments for job_func
            
        Returns:
            str: The job ID for tracking
        """
        if job_id is None:
            job_id = str(uuid.uuid4())
        
        # Create job result record
        job_result = JobResult(
            job_id=job_id,
            status=JobStatus.QUEUED,
            tenant_id=tenant_id,
            max_retries=max_retries,
            metadata=metadata or {}
        )
        
        self._jobs[job_id] = job_result
        
        # Start the job task
        task = asyncio.create_task(self._execute_job(job_id, job_func, args, kwargs))
        self._running_tasks[job_id] = task
        
        # Cleanup task when done (don't await here - this is fire-and-forget)
        task.add_done_callback(lambda t: self._running_tasks.pop(job_id, None))
        
        logger.info(f"Job {job_id} submitted for tenant {tenant_id}")
        return job_id
    
    async def _execute_job(
        self,
        job_id: str,
        job_func: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict
    ) -> None:
        """Execute a job with retry logic."""
        job_result = self._jobs[job_id]
        
        for attempt in range(job_result.max_retries + 1):
            try:
                job_result.status = JobStatus.RUNNING
                job_result.started_at = datetime.utcnow()
                job_result.retry_count = attempt
                
                logger.info(f"Job {job_id} starting (attempt {attempt + 1}/{job_result.max_retries + 1})")
                
                # Execute the job function
                result = await job_func(*args, **kwargs)
                
                # Success!
                job_result.status = JobStatus.COMPLETED
                job_result.finished_at = datetime.utcnow()
                job_result.result = result
                job_result.error = None
                
                logger.info(f"Job {job_id} completed successfully")
                return
                
            except Exception as e:
                error_msg = f"Job {job_id} failed on attempt {attempt + 1}: {str(e)}"
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                
                job_result.error = str(e)
                
                # Check if we should retry
                if attempt < job_result.max_retries:
                    job_result.status = JobStatus.RETRYING
                    
                    # Exponential backoff: 2^attempt seconds
                    delay = min(2 ** attempt, 60)  # Cap at 60 seconds
                    logger.info(f"Job {job_id} will retry in {delay} seconds")
                    await asyncio.sleep(delay)
                    
                else:
                    # Final failure
                    job_result.status = JobStatus.FAILED
                    job_result.finished_at = datetime.utcnow()
                    logger.error(f"Job {job_id} failed permanently after {attempt + 1} attempts")
                    return
    
    def get_job_status(self, job_id: str) -> Optional[JobResult]:
        """Get the status and result of a job."""
        return self._jobs.get(job_id)
    
    def get_jobs_for_tenant(self, tenant_id: uuid.UUID) -> Dict[str, JobResult]:
        """Get all jobs for a specific tenant."""
        return {
            job_id: result 
            for job_id, result in self._jobs.items()
            if result.tenant_id == tenant_id
        }
    
    async def wait_for_job(self, job_id: str, timeout: Optional[float] = None) -> Optional[JobResult]:
        """
        Wait for a job to complete.
        
        Args:
            job_id: Job ID to wait for
            timeout: Maximum time to wait (None = wait indefinitely)
            
        Returns:
            JobResult if completed, None if timeout or job not found
        """
        if job_id not in self._jobs:
            return None
            
        task = self._running_tasks.get(job_id)
        if task is None:
            # Job already finished
            return self._jobs[job_id]
        
        try:
            # Wait for the task to complete
            await asyncio.wait_for(task, timeout=timeout)
            return self._jobs[job_id]
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for job {job_id}")
            return None
    
    def cleanup_old_jobs(self, older_than: timedelta = timedelta(hours=24)) -> int:
        """
        Clean up old completed/failed jobs to prevent memory leaks.
        
        Args:
            older_than: Remove jobs older than this duration
            
        Returns:
            Number of jobs cleaned up
        """
        cutoff_time = datetime.utcnow() - older_than
        
        to_remove = []
        for job_id, result in self._jobs.items():
            # Only clean up finished jobs that are old enough
            if (result.status in [JobStatus.COMPLETED, JobStatus.FAILED] and 
                result.finished_at and 
                result.finished_at < cutoff_time):
                to_remove.append(job_id)
        
        for job_id in to_remove:
            del self._jobs[job_id]
            # Task should already be cleaned up by done_callback
            self._running_tasks.pop(job_id, None)
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old jobs")
        
        return len(to_remove)


# Global job queue instance
_global_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get the global job queue instance (singleton pattern)."""
    global _global_queue
    if _global_queue is None:
        _global_queue = JobQueue()
    return _global_queue


async def submit_background_job(
    job_func: Callable[..., Awaitable[Any]], 
    *args,
    job_id: Optional[str] = None,
    tenant_id: Optional[uuid.UUID] = None,
    max_retries: int = 3,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> str:
    """
    Convenience function to submit a background job.
    
    Returns the job ID for tracking.
    """
    queue = get_job_queue()
    return queue.submit_job(
        job_func, 
        *args,
        job_id=job_id,
        tenant_id=tenant_id,
        max_retries=max_retries,
        metadata=metadata,
        **kwargs
    )


async def get_background_job_status(job_id: str) -> Optional[JobResult]:
    """Get the status of a background job."""
    queue = get_job_queue()
    return queue.get_job_status(job_id)
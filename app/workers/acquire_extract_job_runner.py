"""Worker runner for acquire_extract_async jobs with safe locking.

Uses SELECT FOR UPDATE SKIP LOCKED via claim_next_job to ensure only one
worker claims a job at a time. Designed for short-running loops and tests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Optional

from app.db.session import get_async_session_context
from app.services.company_research_service import CompanyResearchService

logger = logging.getLogger(__name__)


class AcquireExtractJobRunner:
    """Poll and execute acquire_extract_async jobs."""

    def __init__(self, worker_id: Optional[str] = None, poll_interval: float = 1.0) -> None:
        self.worker_id = worker_id or f"acq-extract-{socket.gethostname()}-{os.getpid()}"
        self.poll_interval = poll_interval
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> bool:
        """Claim and execute a single job if available."""
        async with get_async_session_context() as session:
            service = CompanyResearchService(session)
            job = await service.claim_next_job(self.worker_id, job_type="acquire_extract_async")
            if not job:
                return False

            logger.info("Worker %s running job %s", self.worker_id, job.id)
            await service.execute_acquire_extract_job(str(job.tenant_id), job.id, worker_id=self.worker_id)
            return True

    async def run_forever(self) -> None:
        """Poll indefinitely until stopped, respecting poll_interval when idle."""
        while not self._stop_event.is_set():
            processed = await self.run_once()
            if processed:
                continue

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue


def get_default_runner(worker_id: Optional[str] = None, poll_interval: float = 1.0) -> AcquireExtractJobRunner:
    return AcquireExtractJobRunner(worker_id=worker_id, poll_interval=poll_interval)

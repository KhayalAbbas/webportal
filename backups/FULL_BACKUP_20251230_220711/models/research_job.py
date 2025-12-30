"""
Research job queue model for durable background processing.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Index, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class ResearchJob(TenantScopedModel):
    """
    Durable job queue for background research processing.
    
    Provides persistent job storage with locking mechanisms for multi-worker
    environments and recovery after process restarts.
    """
    
    __tablename__ = "research_jobs"
    
    # Link to the research run that triggered this job
    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    
    # Job type identifier (e.g., "ingest_bundle")
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Job execution status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    
    # Retry tracking
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True, index=True)
    
    # Worker locking mechanism
    locked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True, index=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    
    # Error tracking
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Job payload data
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    __table_args__ = (
        # Efficient job polling by status within tenant
        Index("ix_research_jobs_tenant_status", "tenant_id", "status"),
        
        # Lock management indexes
        Index("ix_research_jobs_locked", "locked_at", "locked_by"),
        
        # Cleanup queries by run
        Index("ix_research_jobs_run_status", "run_id", "status"),
    )
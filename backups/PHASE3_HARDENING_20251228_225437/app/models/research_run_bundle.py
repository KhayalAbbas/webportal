"""
Research Run Bundle model.
"""

from datetime import datetime
from typing import Dict, Any
from uuid import UUID

from sqlalchemy import String, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class ResearchRunBundle(TenantScopedModel):
    """
    Stored bundle JSON for research runs.
    
    Append-only table that stores the accepted bundle JSON for audit,
    re-download, and idempotent re-ingestion.
    """
    
    __tablename__ = "research_run_bundles"
    
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    
    bundle_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    
    bundle_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    
    __table_args__ = (
        # One bundle per run (can update by inserting new record)
        UniqueConstraint("tenant_id", "run_id", name="uq_research_run_bundles_run"),
        # Index for fast lookup by SHA256
        Index("ix_research_run_bundles_sha256", "tenant_id", "bundle_sha256"),
    )
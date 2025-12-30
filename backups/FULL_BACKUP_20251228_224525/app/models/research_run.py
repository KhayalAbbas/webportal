"""
Research run ledger models for Phase 3 orchestration.

Tracks AI-run uploads (append-only) without executing external work.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Index, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class ResearchRun(TenantScopedModel):
    """Lightweight ledger for orchestrated AI runs."""

    __tablename__ = "research_runs"

    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )

    # Optional link to the Phase 2 run we ingest into
    company_research_run_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_research_runs.id"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued", index=True)

    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    rank_spec: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    plan_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    idempotency_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bundle_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_research_runs_created", "tenant_id", "created_at"),
        Index("ix_research_runs_status", "tenant_id", "status"),
        Index("ix_research_runs_company_run", "company_research_run_id"),
        # Note: Partial unique constraint created via raw SQL in migration
    )


class ResearchRunStep(TenantScopedModel):
    """Uploaded steps for a research run (append-only ledger)."""

    __tablename__ = "research_run_steps"

    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    step_key: Mapped[str] = mapped_column(String(200), nullable=False)
    step_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ok")

    inputs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    outputs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    provider_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    output_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_research_run_steps_run", "tenant_id", "run_id"),
        UniqueConstraint("tenant_id", "run_id", "step_key", name="uq_research_run_steps_key"),
    )

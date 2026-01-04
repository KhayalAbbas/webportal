"""
AI_EnrichmentRecord model.

Stores AI-generated enrichments for candidates, companies, roles, and documents.
"""

import uuid
from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class AIEnrichmentRecord(TenantScopedModel):
    """
    AI_EnrichmentRecord table - stores AI-generated data.
    
    When AI processes a candidate, company, role, or document,
    the results (summaries, tags, competency maps, etc.) are stored here.
    """
    
    __tablename__ = "ai_enrichment_record"
    
    # What type of entity was enriched (CANDIDATE, COMPANY, ROLE, DOCUMENT)
    target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # ID of the entity that was enriched
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    
    # Which AI model was used (e.g., "gpt-4", "claude-3")
    model_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Type of enrichment (e.g., "SUMMARY", "COMPETENCY_MAP", "TAGGING")
    enrichment_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # The actual enrichment data as JSON
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Phase 4.11: research provenance and idempotency
    company_research_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        "company_research_run_id",
        UUID(as_uuid=True),
        nullable=True,
    )

    purpose: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    provider: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    input_scope_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "purpose",
            "provider",
            "content_hash",
            "target_id",
            "target_type",
            name="uq_ai_enrichment_content_hash",
        ),
    )

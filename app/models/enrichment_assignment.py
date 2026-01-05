"""
EnrichmentAssignment model.

Stores evidence-backed enrichment field assignments for canonical entities.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import String, Text, UniqueConstraint, Index, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class EnrichmentAssignment(TenantScopedModel):
    """Normalized enrichment assignment tied to canonical entities with evidence."""

    __tablename__ = "enrichment_assignments"

    target_entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    target_canonical_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_normalized: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    derived_by: Mapped[str] = mapped_column(String(50), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_scope_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "target_entity_type",
            "target_canonical_id",
            "field_key",
            "content_hash",
            "source_document_id",
            name="uq_enrichment_assignment_idempotent",
        ),
        Index(
            "ix_enrichment_assignments_tenant_target",
            "tenant_id",
            "target_entity_type",
            "target_canonical_id",
        ),
        Index("ix_enrichment_assignments_source_doc", "source_document_id"),
    )

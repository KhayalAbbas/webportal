"""
CandidateContactPoint model.

Stores normalized email/phone contact points for candidates with provenance.
"""

import uuid
from typing import Optional

from sqlalchemy import String, Boolean, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class CandidateContactPoint(TenantScopedModel):
    """
    CandidateContactPoint table - normalized emails/phones gathered from enrichment or manual entry.
    """

    __tablename__ = "candidate_contact_point"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate.id"),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    value_raw: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    value_normalized: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    label: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    provider: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )

    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_document.id"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "candidate_id",
            "kind",
            "value_normalized",
            name="uq_candidate_contact_point_value",
        ),
        Index("ix_candidate_contact_point_candidate", "tenant_id", "candidate_id"),
        Index("ix_candidate_contact_point_normalized", "tenant_id", "value_normalized"),
    )

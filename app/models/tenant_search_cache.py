"""
TenantSearchCache model.

Stores normalized search requests and cached SourceDocument links per tenant.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel


class TenantSearchCache(TenantScopedModel):
    """Per-tenant cache of normalized search results."""

    __tablename__ = "tenant_search_cache"

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(512), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_document.id"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    source_document = relationship("SourceDocument", lazy="joined")

    __table_args__ = (
        Index("uq_search_cache_key", "tenant_id", "provider", "cache_key", unique=True),
        Index("ix_search_cache_expires", "expires_at"),
        Index("ix_search_cache_request_hash", "tenant_id", "provider", "request_hash"),
    )

"""
SourceDocument model.

Stores documents collected during research (PDFs, web pages, etc.).
"""

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.research_event import ResearchEvent


class SourceDocument(TenantScopedModel):
    """
    SourceDocument table - stores documents from research.
    
    These could be PDFs, HTML pages, transcripts, etc.
    The actual file is stored in object storage, referenced by storage_path.
    """
    
    __tablename__ = "source_document"
    
    # Link to the research event that found this document
    research_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_event.id"),
        nullable=False,
    )
    
    # Type of document (e.g., "PDF", "HTML", "TEXT", "TRANSCRIPT")
    document_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # Document title
    title: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Original URL where the document was found
    url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )
    
    # Path in object storage (e.g., S3, Azure Blob, etc.)
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )
    
    # Extracted text content (for searching)
    text_content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Additional metadata as JSON
    # Note: Using 'doc_metadata' instead of 'metadata' (reserved by SQLAlchemy)
    doc_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata",  # Column name in database is still 'metadata'
        JSONB,
        nullable=True,
    )

    # Optional content hash for deduplication/search caching
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    
    # Relationship to research event
    research_event: Mapped["ResearchEvent"] = relationship(
        "ResearchEvent",
        back_populates="source_documents",
    )

    __table_args__ = (
        Index("ix_source_document_tenant_content_hash", "tenant_id", "content_hash"),
    )

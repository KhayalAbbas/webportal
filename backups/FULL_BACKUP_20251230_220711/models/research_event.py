"""
ResearchEvent model.

Tracks research activities from various sources (web, LinkedIn, etc.).
This is the foundation for the Agentic Research Engine.
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.source_document import SourceDocument


class ResearchEvent(TenantScopedModel):
    """
    ResearchEvent table - tracks research activities.
    
    When the system researches a candidate, company, or role,
    the source and results are logged here.
    """
    
    __tablename__ = "research_event"
    
    # Where the research came from (e.g., "WEB", "LINKEDIN", "INTERNAL_DB")
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # URL of the source (if applicable)
    source_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )
    
    # What type of entity was researched (CANDIDATE, COMPANY, or ROLE)
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # ID of the entity that was researched
    # Stored as UUID - can reference Candidate, Company, or Role
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    
    # Raw data from the research (stored as JSON)
    raw_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Documents found during this research
    source_documents: Mapped[List["SourceDocument"]] = relationship(
        "SourceDocument",
        back_populates="research_event",
        lazy="selectin",
    )

"""
CandidateAssignment model.

Tracks candidates assigned to roles.
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.role import Role
    from app.models.pipeline_stage import PipelineStage


class CandidateAssignment(TenantScopedModel):
    """
    CandidateAssignment table - tracks candidates assigned to roles.
    """
    
    __tablename__ = "candidate_assignment"
    
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate.id"),
        nullable=False,
    )
    
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id"),
        nullable=False,
    )
    
    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    is_hot: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    
    date_entered: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    start_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    current_stage_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_stage.id"),
        nullable=True,
    )
    
    source: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    candidate: Mapped["Candidate"] = relationship(
        "Candidate",
        lazy="selectin",
    )
    
    role: Mapped["Role"] = relationship(
        "Role",
        lazy="selectin",
    )
    
    current_stage: Mapped[Optional["PipelineStage"]] = relationship(
        "PipelineStage",
        lazy="selectin",
    )

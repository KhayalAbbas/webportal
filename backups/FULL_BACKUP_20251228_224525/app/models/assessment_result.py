"""
AssessmentResult model.

Stores assessment/psychometric test results for candidates.
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.role import Role


class AssessmentResult(TenantScopedModel):
    """
    AssessmentResult table - stores assessment and psychometric test results.
    """
    
    __tablename__ = "assessment_result"
    
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate.id"),
        nullable=False,
    )
    
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id"),
        nullable=True,
    )
    
    assessment_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    provider: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    score_numeric: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    score_label: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    taken_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationships
    candidate: Mapped["Candidate"] = relationship(
        "Candidate",
        foreign_keys=[candidate_id],
        lazy="selectin",
    )
    
    role: Mapped[Optional["Role"]] = relationship(
        "Role",
        lazy="selectin",
    )

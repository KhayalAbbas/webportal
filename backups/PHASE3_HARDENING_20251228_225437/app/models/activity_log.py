"""
ActivityLog model.

Tracks all activities related to candidates, roles, and contacts.
This is your audit trail / activity history.
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.role import Role
    from app.models.contact import Contact


class ActivityLog(TenantScopedModel):
    """
    ActivityLog table - tracks all activities in the system.
    
    Records things like notes, calls, emails, status changes, etc.
    Can be linked to a candidate, role, and/or contact.
    """
    
    __tablename__ = "activity_log"
    
    # Optional foreign keys - an activity can relate to any combination
    candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate.id"),
        nullable=True,
    )
    
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id"),
        nullable=True,
    )
    
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact.id"),
        nullable=True,
    )
    
    # Type of activity (e.g., "NOTE", "CALL", "EMAIL", "STATUS_CHANGE")
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # The actual content/message of the activity
    message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Who created this activity (username or email)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # When the activity actually occurred (might differ from created_at)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    # Relationships
    candidate: Mapped[Optional["Candidate"]] = relationship(
        "Candidate",
        back_populates="activity_logs",
    )
    
    role: Mapped[Optional["Role"]] = relationship(
        "Role",
        back_populates="activity_logs",
    )
    
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact",
        back_populates="activity_logs",
    )

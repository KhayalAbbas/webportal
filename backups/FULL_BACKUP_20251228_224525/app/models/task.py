"""
Task model.

Represents a task or to-do item in the system.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class Task(TenantScopedModel):
    """
    Task table - represents tasks or to-do items.
    """
    
    __tablename__ = "task"
    
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    related_entity_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    related_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    assigned_to_user: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
    )
    
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

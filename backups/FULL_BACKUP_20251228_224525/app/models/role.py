"""
Role (Mandate) model.

Represents a job opening/position that needs to be filled.
"""

import uuid
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.activity_log import ActivityLog


class Role(TenantScopedModel):
    """
    Role table - represents a job opening/mandate.
    
    This is the position that candidates are being recruited for.
    """
    
    __tablename__ = "role"
    
    # Foreign key to the company with this opening
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company.id"),
        nullable=False,
    )
    
    # Job title (e.g., "Senior Software Engineer")
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Function/department (e.g., "Engineering", "Marketing")
    function: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Job location
    location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Status: 'open', 'on_hold', or 'closed'
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
    )
    
    # Seniority level (e.g., "Junior", "Mid", "Senior", "Director")
    seniority_level: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Full job description
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationship to company
    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="roles",
    )
    
    # Activity logs for this role
    activity_logs: Mapped[List["ActivityLog"]] = relationship(
        "ActivityLog",
        back_populates="role",
        lazy="selectin",
    )
    
    # Composite index for faster queries within a tenant
    __table_args__ = (
        Index("ix_role_tenant_company", "tenant_id", "company_id"),
    )

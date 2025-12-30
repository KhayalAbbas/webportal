"""
Contact model.

Represents a person at a client company (executive, hiring manager, etc.).
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Index, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.activity_log import ActivityLog


class Contact(TenantScopedModel):
    """
    Contact table - represents a person at a client company.
    
    This could be an executive, hiring manager, HR contact, etc.
    """
    
    __tablename__ = "contact"
    
    # Foreign key to the company this contact works at
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company.id"),
        nullable=False,
    )
    
    # Contact's name
    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Contact information
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Their job title
    role_title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    
    # Additional notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # BD fields
    bd_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    bd_owner: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    work_anniversary_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationship to company
    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="contacts",
    )
    
    # Activity logs for this contact
    activity_logs: Mapped[List["ActivityLog"]] = relationship(
        "ActivityLog",
        back_populates="contact",
        lazy="selectin",
    )
    
    # Composite index for faster queries within a tenant
    __table_args__ = (
        Index("ix_contact_tenant_company", "tenant_id", "company_id"),
    )

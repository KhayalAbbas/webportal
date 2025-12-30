"""
Company model.

Represents a client company that has job openings/roles to fill.
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Index, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.role import Role


class Company(TenantScopedModel):
    """
    Company table - represents a client company.
    
    A company can have multiple contacts (executives, hiring managers)
    and multiple roles (job openings).
    """
    
    __tablename__ = "company"
    
    # Company name
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Industry (e.g., "Technology", "Healthcare", "Finance")
    industry: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Where the company is headquartered
    headquarters_location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Company website URL
    website: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Additional notes about the company
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # BD fields
    bd_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    bd_last_contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    bd_owner: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    is_prospect: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    
    is_client: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    
    # Relationships - these let you access related data easily
    # Example: company.contacts gives you all contacts at this company
    contacts: Mapped[List["Contact"]] = relationship(
        "Contact",
        back_populates="company",
        lazy="selectin",
    )
    
    roles: Mapped[List["Role"]] = relationship(
        "Role",
        back_populates="company",
        lazy="selectin",
    )

"""
BDOpportunity model.

Represents a business development opportunity.
"""

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.contact import Contact


class BDOpportunity(TenantScopedModel):
    """
    BDOpportunity table - represents business development opportunities.
    """
    
    __tablename__ = "bd_opportunity"
    
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company.id"),
        nullable=False,
    )
    
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact.id"),
        nullable=True,
    )
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="open",
    )
    
    stage: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    estimated_value: Mapped[Optional[float]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
    )
    
    currency: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default="USD",
    )
    
    probability: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )
    
    lost_reason: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    lost_reason_detail: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    company: Mapped["Company"] = relationship(
        "Company",
        lazy="selectin",
    )
    
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact",
        lazy="selectin",
    )

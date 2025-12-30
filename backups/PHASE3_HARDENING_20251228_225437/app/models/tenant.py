"""
Tenant model.

A Tenant represents a customer/organization using the ATS system.
Each tenant's data is isolated from other tenants.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    """
    Tenant table - represents a customer organization.
    
    Note: Tenant doesn't inherit from TenantScopedModel because
    the Tenant table itself doesn't belong to a tenant.
    """
    
    __tablename__ = "tenant"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Tenant name (company/organization name)
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    # Status: 'active' or 'inactive'
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

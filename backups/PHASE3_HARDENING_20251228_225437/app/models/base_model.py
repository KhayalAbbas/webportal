"""
Base model with common fields.

All tenant-scoped tables inherit from this to get:
- id (UUID primary key)
- tenant_id (for multi-tenancy)
- created_at (when the record was created)
- updated_at (when the record was last modified)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantScopedModel(Base):
    """
    Abstract base class for all tenant-scoped models.
    
    This is not a real table - it's a template that other models inherit from.
    Every table that belongs to a tenant will have these fields automatically.
    """
    
    __abstract__ = True  # This means: don't create a table for this class
    
    # Primary key - UUID (universally unique identifier)
    # Each record gets a unique ID that's virtually impossible to duplicate
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Tenant ID - identifies which customer/organization owns this data
    # Indexed for fast lookups when filtering by tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    
    # Timestamps - automatically set when records are created/updated
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

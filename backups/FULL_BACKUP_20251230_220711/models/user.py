"""
User model for authentication and authorization.
"""

import uuid
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class User(Base):
    """
    User table - represents authenticated users in the system.
    
    Users belong to tenants and have roles that determine their permissions.
    """
    
    __tablename__ = "user"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id"),
        nullable=False,
    )
    
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="viewer",
    )
    
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Relationship to tenant
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        lazy="selectin",
    )
    
    # Composite unique constraint: email is unique per tenant
    __table_args__ = (
        Index("ix_user_tenant_email", "tenant_id", "email", unique=True),
    )

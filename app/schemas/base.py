"""
Base Pydantic schemas with common fields.

These are templates that other schemas inherit from.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantScopedBase(BaseModel):
    """
    Base schema for tenant-scoped data.
    
    Used when creating new records - you provide the tenant_id.
    """
    
    tenant_id: str | UUID


class TenantScopedRead(BaseModel):
    """
    Base schema for reading tenant-scoped data.
    
    Includes all the auto-generated fields like id, timestamps, etc.
    """
    
    id: UUID
    tenant_id: str | UUID
    created_at: datetime
    updated_at: datetime
    
    # This tells Pydantic to work with SQLAlchemy models
    model_config = ConfigDict(from_attributes=True)

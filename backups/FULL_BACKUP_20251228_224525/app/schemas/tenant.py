"""
Tenant Pydantic schemas.

These define the data structure for API requests and responses.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
    """Schema for creating a new tenant."""
    
    name: str
    status: str = "active"


class TenantUpdate(BaseModel):
    """Schema for updating a tenant. All fields optional."""
    
    name: Optional[str] = None
    status: Optional[str] = None


class TenantRead(BaseModel):
    """Schema for reading tenant data (API response)."""
    
    id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

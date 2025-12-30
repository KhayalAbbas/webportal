"""
ActivityLog Pydantic schemas.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class ActivityLogCreate(TenantScopedBase):
    """Schema for creating a new activity log."""
    
    candidate_id: Optional[UUID] = None
    role_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    type: str
    message: Optional[str] = None
    created_by: Optional[str] = None
    occurred_at: Optional[datetime] = None


class ActivityLogUpdate(BaseModel):
    """Schema for updating an activity log. All fields optional."""
    
    type: Optional[str] = None
    message: Optional[str] = None
    occurred_at: Optional[datetime] = None


class ActivityLogRead(TenantScopedRead):
    """Schema for reading activity log data (API response)."""
    
    candidate_id: Optional[UUID] = None
    role_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    type: str
    message: Optional[str] = None
    created_by: Optional[str] = None
    occurred_at: datetime

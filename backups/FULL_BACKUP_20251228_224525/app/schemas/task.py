"""
Task Pydantic schemas.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class TaskCreate(TenantScopedBase):
    """Schema for creating a new task."""
    
    title: str
    description: Optional[str] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[UUID] = None
    assigned_to_user: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str = "pending"


class TaskUpdate(BaseModel):
    """Schema for updating a task. All fields optional."""
    
    title: Optional[str] = None
    description: Optional[str] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[UUID] = None
    assigned_to_user: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    completed_at: Optional[datetime] = None


class TaskRead(TenantScopedRead):
    """Schema for reading task data (API response)."""
    
    title: str
    description: Optional[str] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[UUID] = None
    assigned_to_user: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str
    completed_at: Optional[datetime] = None

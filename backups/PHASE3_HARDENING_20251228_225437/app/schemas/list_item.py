"""
ListItem Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class ListItemCreate(TenantScopedBase):
    """Schema for creating a new list item."""
    
    list_id: UUID
    entity_type: str
    entity_id: UUID


class ListItemUpdate(BaseModel):
    """Schema for updating a list item. All fields optional."""
    
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None


class ListItemRead(TenantScopedRead):
    """Schema for reading list item data (API response)."""
    
    list_id: UUID
    entity_type: str
    entity_id: UUID
    added_at: str

"""
List Pydantic schemas.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class ListCreate(TenantScopedBase):
    """Schema for creating a new list."""
    
    name: str
    type: Optional[str] = None
    description: Optional[str] = None


class ListUpdate(BaseModel):
    """Schema for updating a list. All fields optional."""
    
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class ListRead(TenantScopedRead):
    """Schema for reading list data (API response)."""
    
    name: str
    type: Optional[str] = None
    description: Optional[str] = None

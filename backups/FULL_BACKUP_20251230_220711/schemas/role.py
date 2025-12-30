"""
Role (Mandate) Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class RoleCreate(TenantScopedBase):
    """Schema for creating a new role."""
    
    company_id: UUID
    title: str
    function: Optional[str] = None
    location: Optional[str] = None
    status: str = "open"
    seniority_level: Optional[str] = None
    description: Optional[str] = None


class RoleUpdate(BaseModel):
    """Schema for updating a role. All fields optional."""
    
    company_id: Optional[UUID] = None
    title: Optional[str] = None
    function: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    seniority_level: Optional[str] = None
    description: Optional[str] = None


class RoleRead(TenantScopedRead):
    """Schema for reading role data (API response)."""
    
    company_id: UUID
    title: str
    function: Optional[str] = None
    location: Optional[str] = None
    status: str
    seniority_level: Optional[str] = None
    description: Optional[str] = None

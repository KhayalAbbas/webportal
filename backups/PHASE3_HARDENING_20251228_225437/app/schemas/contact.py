"""
Contact Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class ContactCreate(TenantScopedBase):
    """Schema for creating a new contact."""
    
    company_id: UUID
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role_title: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_owner: Optional[str] = None
    date_of_birth: Optional[str] = None
    work_anniversary_date: Optional[str] = None


class ContactUpdate(BaseModel):
    """Schema for updating a contact. All fields optional."""
    
    company_id: Optional[UUID] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role_title: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_owner: Optional[str] = None
    date_of_birth: Optional[str] = None
    work_anniversary_date: Optional[str] = None


class ContactRead(TenantScopedRead):
    """Schema for reading contact data (API response)."""
    
    company_id: UUID
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role_title: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_owner: Optional[str] = None
    date_of_birth: Optional[str] = None
    work_anniversary_date: Optional[str] = None

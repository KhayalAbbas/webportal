""" Company Pydantic schemas.
"""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class CompanyCreate(TenantScopedBase):
    """Schema for creating a new company."""
    
    name: str
    industry: Optional[str] = None
    headquarters_location: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_last_contacted_at: Optional[datetime] = None
    bd_owner: Optional[str] = None
    is_prospect: bool = False
    is_client: bool = False


class CompanyUpdate(BaseModel):
    """Schema for updating a company. All fields optional."""
    
    name: Optional[str] = None
    industry: Optional[str] = None
    headquarters_location: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_last_contacted_at: Optional[datetime] = None
    bd_owner: Optional[str] = None
    is_prospect: Optional[bool] = None
    is_client: Optional[bool] = None


class CompanyRead(TenantScopedRead):
    """Schema for reading company data (API response)."""
    
    name: str
    industry: Optional[str] = None
    headquarters_location: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    bd_status: Optional[str] = None
    bd_last_contacted_at: Optional[datetime] = None
    bd_owner: Optional[str] = None
    is_prospect: bool = False
    is_client: bool = False

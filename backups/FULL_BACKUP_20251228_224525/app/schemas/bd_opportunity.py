"""
BDOpportunity Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class BDOpportunityCreate(TenantScopedBase):
    """Schema for creating a new BD opportunity."""
    
    company_id: UUID
    contact_id: Optional[UUID] = None
    status: str = "open"
    stage: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: Optional[str] = "USD"
    probability: Optional[int] = None
    lost_reason: Optional[str] = None
    lost_reason_detail: Optional[str] = None


class BDOpportunityUpdate(BaseModel):
    """Schema for updating a BD opportunity. All fields optional."""
    
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: Optional[str] = None
    probability: Optional[int] = None
    lost_reason: Optional[str] = None
    lost_reason_detail: Optional[str] = None


class BDOpportunityRead(TenantScopedRead):
    """Schema for reading BD opportunity data (API response)."""
    
    company_id: UUID
    contact_id: Optional[UUID] = None
    status: str
    stage: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: Optional[str] = None
    probability: Optional[int] = None
    lost_reason: Optional[str] = None
    lost_reason_detail: Optional[str] = None

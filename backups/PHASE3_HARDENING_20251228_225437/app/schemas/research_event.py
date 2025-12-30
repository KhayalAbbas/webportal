"""
ResearchEvent Pydantic schemas.
"""

from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class ResearchEventCreate(TenantScopedBase):
    """Schema for creating a new research event."""
    
    source_type: str
    source_url: Optional[str] = None
    entity_type: str
    entity_id: UUID
    raw_payload: Optional[dict] = None


class ResearchEventUpdate(BaseModel):
    """Schema for updating a research event. All fields optional."""
    
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    raw_payload: Optional[dict] = None


class ResearchEventRead(TenantScopedRead):
    """Schema for reading research event data (API response)."""
    
    source_type: str
    source_url: Optional[str] = None
    entity_type: str
    entity_id: UUID
    raw_payload: Optional[dict] = None

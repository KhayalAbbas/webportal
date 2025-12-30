"""
AI_EnrichmentRecord Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class AIEnrichmentRecordCreate(TenantScopedBase):
    """Schema for creating a new AI enrichment record."""
    model_config = ConfigDict(protected_namespaces=())
    
    target_type: str
    target_id: UUID
    model_name: Optional[str] = None
    enrichment_type: str
    payload: Optional[dict] = None


class AIEnrichmentRecordUpdate(BaseModel):
    """Schema for updating an AI enrichment record. All fields optional."""
    model_config = ConfigDict(protected_namespaces=())
    
    model_name: Optional[str] = None
    enrichment_type: Optional[str] = None
    payload: Optional[dict] = None


class AIEnrichmentRecordRead(TenantScopedRead):
    """Schema for reading AI enrichment record data (API response)."""
    model_config = ConfigDict(protected_namespaces=())
    
    target_type: str
    target_id: UUID
    model_name: Optional[str] = None
    enrichment_type: str
    payload: Optional[dict] = None

"""
Schemas for AIEnrichmentRecord.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class AIEnrichmentCreate(BaseModel):
    """Schema for creating a new AI enrichment record."""
    model_config = ConfigDict(protected_namespaces=())
    
    target_type: str  # CANDIDATE, COMPANY, ROLE, DOCUMENT
    target_id: UUID
    model_name: str
    enrichment_type: str  # SUMMARY, COMPETENCY_MAP, TAGGING, RISK_FLAGS, OTHER
    payload: dict
    company_research_run_id: Optional[UUID] = None
    purpose: Optional[str] = None
    provider: Optional[str] = None
    input_scope_hash: Optional[str] = None
    content_hash: Optional[str] = None
    source_document_id: Optional[UUID] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


class AIEnrichmentUpdate(BaseModel):
    """Schema for updating an AI enrichment record."""
    model_config = ConfigDict(protected_namespaces=())
    
    target_type: Optional[str] = None
    target_id: Optional[UUID] = None
    model_name: Optional[str] = None
    enrichment_type: Optional[str] = None
    payload: Optional[dict] = None
    company_research_run_id: Optional[UUID] = None
    purpose: Optional[str] = None
    provider: Optional[str] = None
    input_scope_hash: Optional[str] = None
    content_hash: Optional[str] = None
    source_document_id: Optional[UUID] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


class AIEnrichmentRead(BaseModel):
    """Schema for reading an AI enrichment record."""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    
    id: UUID
    tenant_id: UUID
    target_type: str
    target_id: UUID
    model_name: str
    enrichment_type: str
    payload: dict
    created_at: datetime
    company_research_run_id: Optional[UUID] = None
    purpose: Optional[str] = None
    provider: Optional[str] = None
    input_scope_hash: Optional[str] = None
    content_hash: Optional[str] = None
    source_document_id: Optional[UUID] = None
    status: Optional[str] = None
    error_message: Optional[str] = None

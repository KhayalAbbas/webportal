"""
SourceDocument Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class SourceDocumentCreate(TenantScopedBase):
    """Schema for creating a new source document."""
    
    research_event_id: UUID
    document_type: str
    title: Optional[str] = None
    url: Optional[str] = None
    storage_path: Optional[str] = None
    text_content: Optional[str] = None
    doc_metadata: Optional[dict] = None


class SourceDocumentUpdate(BaseModel):
    """Schema for updating a source document. All fields optional."""
    
    document_type: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    storage_path: Optional[str] = None
    text_content: Optional[str] = None
    doc_metadata: Optional[dict] = None


class SourceDocumentRead(TenantScopedRead):
    """Schema for reading source document data (API response)."""
    
    research_event_id: UUID
    document_type: str
    title: Optional[str] = None
    url: Optional[str] = None
    storage_path: Optional[str] = None
    text_content: Optional[str] = None
    doc_metadata: Optional[dict] = None

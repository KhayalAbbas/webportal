"""
Pydantic schemas for CandidateContactPoint.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class CandidateContactPointCreate(TenantScopedBase):
    candidate_id: UUID
    kind: str
    value_raw: str
    value_normalized: str
    label: Optional[str] = None
    is_primary: bool = False
    provider: Optional[str] = None
    confidence: Optional[float] = None
    source_document_id: Optional[UUID] = None


class CandidateContactPointRead(TenantScopedRead):
    candidate_id: UUID
    kind: str
    value_raw: str
    value_normalized: str
    label: Optional[str] = None
    is_primary: bool = False
    provider: Optional[str] = None
    confidence: Optional[float] = None
    source_document_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)

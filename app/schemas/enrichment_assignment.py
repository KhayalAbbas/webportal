"""
Pydantic schemas for enrichment assignments.
"""

from typing import Any, Optional, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


JsonValue = dict | list | str | int | float | bool | None


class EnrichmentAssignmentCreate(TenantScopedBase):
    """Payload to create or upsert an enrichment assignment."""

    target_entity_type: Literal["company", "person"]
    target_canonical_id: UUID
    field_key: str = Field(..., max_length=100)
    value: JsonValue
    value_normalized: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    derived_by: str = Field(..., max_length=50)
    source_document_id: UUID
    input_scope_hash: Optional[str] = Field(default=None, max_length=64)


class EnrichmentAssignmentRead(TenantScopedRead):
    """Read model for enrichment assignments."""

    target_entity_type: str
    target_canonical_id: UUID
    field_key: str
    value: JsonValue
    value_normalized: Optional[str] = None
    confidence: float
    derived_by: str
    source_document_id: UUID
    input_scope_hash: Optional[str] = None
    content_hash: str

    model_config = ConfigDict(from_attributes=True)

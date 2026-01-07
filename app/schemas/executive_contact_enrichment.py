"""
Schemas for executive contact enrichment actions.
"""

from typing import List
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.contact_enrichment import ContactEnrichmentRequest, ProviderEnrichmentResult


class ExecutiveContactEnrichmentResponse(BaseModel):
    executive_id: UUID
    results: List[ProviderEnrichmentResult]


class BulkExecutiveContactEnrichmentRequest(ContactEnrichmentRequest):
    executive_ids: List[UUID] = Field(..., min_length=1, max_length=20)


class BulkExecutiveContactEnrichmentResponseItem(BaseModel):
    executive_id: UUID
    results: List[ProviderEnrichmentResult]


class BulkExecutiveContactEnrichmentResponse(BaseModel):
    items: List[BulkExecutiveContactEnrichmentResponseItem]

"""
Schemas for candidate contact enrichment.
"""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ContactEnrichmentRequest(BaseModel):
    providers: List[str] = Field(default_factory=lambda: ["lusha", "signalhire"])
    mode: str = "mock"
    force: bool = False
    ttl_minutes: int = Field(1440, ge=0, description="TTL window in minutes before re-enrichment is allowed")


class ProviderEnrichmentResult(BaseModel):
    provider: str
    status: str
    added_points: int = 0
    skipped_points: int = 0
    enrichment_id: Optional[UUID] = None
    message: Optional[str] = None
    source_document_id: Optional[UUID] = None


class ContactEnrichmentResponse(BaseModel):
    candidate_id: UUID
    results: List[ProviderEnrichmentResult]

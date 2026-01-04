"""Schemas for external LLM (Grok/mock) company discovery payloads."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class LlmEvidence(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: HttpUrl
    label: Optional[str] = None
    kind: Optional[str] = Field(default=None, pattern=r"^(homepage|annual_report|ranking_list|registry|press_release|investor|other)$")
    snippet: Optional[str] = None
    published_date: Optional[datetime] = None


class LlmCompany(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str
    website_url: Optional[str] = None
    hq_country: Optional[str] = None
    hq_city: Optional[str] = None
    sector: Optional[str] = None
    subsector: Optional[str] = None
    description: Optional[str] = None
    rationale: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: Optional[List[LlmEvidence]] = None


class LlmRunContext(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    query: Optional[str] = None
    geo: Optional[List[str]] = None
    industry: Optional[List[str]] = None
    notes: Optional[str] = None


class LlmDiscoveryPayload(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = Field(default="company_discovery_v1")
    provider: str
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    run_context: Optional[LlmRunContext] = None
    companies: List[LlmCompany] = Field(default_factory=list)

    def canonical_dict(self) -> dict:
        """Return a JSON-serializable dict with stable ordering for hashing."""
        # mode="json" ensures datetime fields are serialized to ISO strings
        return self.model_dump(exclude_none=True, by_alias=True, mode="json")

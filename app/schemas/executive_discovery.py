"""Schemas for external executive discovery payloads."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, HttpUrl


class ExecutiveEvidence(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: Optional[HttpUrl] = None
    label: Optional[str] = None
    kind: Optional[str] = None
    snippet: Optional[str] = None


class ExecutivePerson(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str
    title: Optional[str] = None
    profile_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: List[ExecutiveEvidence] = Field(default_factory=list)


class ExecutiveCompanyEntry(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    company_name: str
    company_normalized: Optional[str] = None
    company_website: Optional[str] = None
    executives: List[ExecutivePerson] = Field(default_factory=list)


class ExecutiveDiscoveryPayload(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = Field(default="executive_discovery_v1")
    provider: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[str] = None
    query: Optional[str] = None
    run_metadata: Optional[Dict[str, Any]] = None
    companies: List[ExecutiveCompanyEntry] = Field(default_factory=list)

    def canonical_dict(self) -> dict:
        """Return JSON-serializable dict with stable ordering for hashing."""
        return self.model_dump(exclude_none=True, by_alias=True, mode="json")

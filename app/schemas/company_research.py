"""
Company Research Pydantic schemas.

Schemas for company discovery and agentic sourcing engine API.
"""

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


# ============================================================================
# Company Research Run Schemas
# ============================================================================

class CompanyResearchRunCreate(BaseModel):
    """Schema for creating a new company research run."""
    
    role_mandate_id: UUID
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    sector: str = Field(..., max_length=100)
    region_scope: Optional[List[str]] = None  # List of ISO country codes
    config: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(default="planned", max_length=50)


class CompanyResearchRunUpdate(BaseModel):
    """Schema for updating a company research run."""
    
    status: Optional[str] = Field(None, max_length=50)
    summary: Optional[str] = None
    error_message: Optional[str] = None
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CompanyResearchRunRead(TenantScopedRead):
    """Schema for reading company research run data."""
    
    role_mandate_id: UUID
    name: str
    description: Optional[str] = None
    status: str
    sector: str
    region_scope: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    error_message: Optional[str] = None
    last_error: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class CompanyResearchRunPlanRead(TenantScopedRead):
    """Schema for viewing deterministic run plan."""

    run_id: UUID
    version: int
    plan_json: Dict[str, Any]
    locked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CompanyResearchRunStepRead(TenantScopedRead):
    """Schema for viewing run steps."""

    run_id: UUID
    step_key: str
    step_order: int
    status: str
    attempt_count: int = 0
    max_attempts: int
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None


# ============================================================================
# Company Prospect Schemas
# ============================================================================

class CompanyProspectCreate(BaseModel):
    """Schema for creating a new company prospect."""
    
    company_research_run_id: UUID
    role_mandate_id: UUID
    name_raw: str = Field(..., max_length=500)
    name_normalized: str = Field(..., max_length=500)
    website_url: Optional[str] = Field(None, max_length=500)
    hq_country: Optional[str] = Field(None, max_length=2)
    hq_city: Optional[str] = Field(None, max_length=200)
    sector: str = Field(..., max_length=100)
    subsector: Optional[str] = Field(None, max_length=100)
    employees_band: Optional[str] = Field(None, max_length=50)
    revenue_band_usd: Optional[str] = Field(None, max_length=50)
    countries_of_operation: Optional[List[str]] = None
    description: Optional[str] = None
    data_confidence: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    relevance_score: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    evidence_score: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    manual_priority: Optional[int] = None
    is_pinned: Optional[bool] = Field(default=False)
    status: Optional[str] = Field(default="new", max_length=50)
    discovered_by: Optional[str] = Field(default="internal", max_length=50)
    verification_status: Optional[str] = Field(default="unverified", max_length=50)
    exec_search_enabled: Optional[bool] = Field(default=False)
    review_status: Optional[str] = Field(default="new", max_length=50)


class CompanyProspectUpdateManual(BaseModel):
    """Schema for manually updating company prospect ranking/status."""
    
    manual_priority: Optional[int] = None
    manual_notes: Optional[str] = None
    is_pinned: Optional[bool] = None
    status: Optional[str] = Field(None, max_length=50)
    discovered_by: Optional[str] = Field(default=None, max_length=50)
    verification_status: Optional[str] = Field(default=None, max_length=50)
    exec_search_enabled: Optional[bool] = None
    review_status: Optional[str] = Field(default=None, max_length=50)


class CompanyProspectUpdate(BaseModel):
    """Schema for updating company prospect (system use)."""
    
    name_raw: Optional[str] = Field(None, max_length=500)
    name_normalized: Optional[str] = Field(None, max_length=500)
    website_url: Optional[str] = Field(None, max_length=500)
    hq_country: Optional[str] = Field(None, max_length=2)
    hq_city: Optional[str] = Field(None, max_length=200)
    sector: Optional[str] = Field(None, max_length=100)
    subsector: Optional[str] = Field(None, max_length=100)
    employees_band: Optional[str] = Field(None, max_length=50)
    revenue_band_usd: Optional[str] = Field(None, max_length=50)
    countries_of_operation: Optional[List[str]] = None
    description: Optional[str] = None
    data_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    evidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: Optional[str] = Field(None, max_length=50)
    approved_by_user_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    normalized_company_id: Optional[UUID] = None


class CompanyProspectRead(TenantScopedRead):
    """Schema for reading company prospect data."""
    
    company_research_run_id: UUID
    role_mandate_id: UUID
    name_raw: str
    name_normalized: str
    website_url: Optional[str] = None
    hq_country: Optional[str] = None
    hq_city: Optional[str] = None
    sector: str
    subsector: Optional[str] = None
    employees_band: Optional[str] = None
    revenue_band_usd: Optional[str] = None
    countries_of_operation: Optional[List[str]] = None
    description: Optional[str] = None
    data_confidence: float
    relevance_score: float
    evidence_score: float
    manual_priority: Optional[int] = None
    manual_notes: Optional[str] = None
    is_pinned: bool
    status: str
    approved_by_user_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    normalized_company_id: Optional[UUID] = None
    discovered_by: str
    verification_status: str
    exec_search_enabled: bool
    review_status: str


class CompanyProspectReviewUpdate(BaseModel):
    """Schema for updating a prospect's review gate status."""

    review_status: str = Field(..., max_length=50)


# ============================================================================
# Company Prospect Evidence Schemas
# ============================================================================

class CompanyProspectEvidenceCreate(TenantScopedBase):
    """Schema for creating company prospect evidence."""
    
    company_prospect_id: UUID
    source_type: str = Field(..., max_length=100)
    source_name: str = Field(..., max_length=500)
    source_url: Optional[str] = None
    list_name: Optional[str] = Field(None, max_length=500)
    list_rank_position: Optional[int] = None
    search_query_used: Optional[str] = None
    evidence_weight: Optional[float] = Field(default=0.5, ge=0.0, le=1.0)
    raw_snippet: Optional[str] = None
    source_document_id: Optional[UUID] = None
    source_content_hash: Optional[str] = None


class CompanyProspectEvidenceRead(TenantScopedRead):
    """Schema for reading company prospect evidence."""
    
    company_prospect_id: UUID
    source_type: str
    source_name: str
    source_url: Optional[str] = None
    list_name: Optional[str] = None
    list_rank_position: Optional[int] = None
    search_query_used: Optional[str] = None
    evidence_weight: float
    raw_snippet: Optional[str] = None
    source_document_id: Optional[UUID] = None
    source_content_hash: Optional[str] = None


class SourceDocumentNested(BaseModel):
    """Nested source document schema for use in evidence."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    company_research_run_id: UUID
    title: Optional[str] = None
    url: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: datetime
    fetched_at: Optional[datetime] = None


class CompanyProspectEvidenceWithSource(BaseModel):
    """Evidence schema with nested source document details."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    company_prospect_id: UUID
    source_type: str
    source_name: str
    source_url: Optional[str] = None
    list_name: Optional[str] = None
    list_rank_position: Optional[int] = None
    search_query_used: Optional[str] = None
    evidence_weight: float
    raw_snippet: Optional[str] = None
    source_document_id: Optional[UUID] = None
    source_content_hash: Optional[str] = None
    created_at: datetime
    source_document: Optional[SourceDocumentNested] = None


# ============================================================================
# Company Prospect Metric Schemas
# ============================================================================

class CompanyProspectMetricCreate(TenantScopedBase):
    """Schema for creating company prospect metric."""
    
    company_prospect_id: UUID
    metric_type: str = Field(..., max_length=100)
    value_raw: Optional[float] = None
    currency: Optional[str] = Field(None, max_length=3)
    value_usd: Optional[float] = None
    as_of_year: Optional[int] = None
    source_type: str = Field(..., max_length=100)
    source_url: Optional[str] = None
    data_confidence: Optional[float] = Field(default=0.5, ge=0.0, le=1.0)


class CompanyProspectMetricRead(TenantScopedRead):
    """Schema for reading company prospect metric."""
    
    company_prospect_id: UUID
    metric_type: str
    value_raw: Optional[float] = None
    currency: Optional[str] = None
    value_usd: Optional[float] = None
    as_of_year: Optional[int] = None
    source_type: str
    source_url: Optional[str] = None
    data_confidence: float


# ============================================================================
# Composite/Listing Schemas
# ============================================================================

class CompanyProspectListItem(BaseModel):
    """Minimal schema for listing company prospects."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name_normalized: str
    website_url: Optional[str] = None
    hq_country: Optional[str] = None
    hq_city: Optional[str] = None
    sector: str
    subsector: Optional[str] = None
    employees_band: Optional[str] = None
    revenue_band_usd: Optional[str] = None
    relevance_score: float
    evidence_score: float
    manual_priority: Optional[int] = None
    is_pinned: bool
    status: str
    review_status: str
    discovered_by: str
    verification_status: str
    exec_search_enabled: bool
    created_at: datetime
    updated_at: datetime


class CompanyProspectWithEvidence(BaseModel):
    """Extended prospect schema with evidence and source documents."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name_normalized: str
    website_url: Optional[str] = None
    hq_country: Optional[str] = None
    hq_city: Optional[str] = None
    sector: str
    subsector: Optional[str] = None
    employees_band: Optional[str] = None
    revenue_band_usd: Optional[str] = None
    relevance_score: float
    evidence_score: float
    manual_priority: Optional[int] = None
    is_pinned: bool
    status: str
    created_at: datetime
    updated_at: datetime
    evidence: List[CompanyProspectEvidenceWithSource] = []


class ProspectSignalEvidence(BaseModel):
    """Why-included evidence derived from enrichment assignments."""

    model_config = ConfigDict(from_attributes=True)

    field_key: str
    value: Any
    value_normalized: Optional[str] = None
    confidence: float
    source_document_id: UUID


class CompanyProspectRanking(BaseModel):
    """Deterministic ranking response with explainability."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name_normalized: str
    normalized_company_id: Optional[UUID] = None
    website_url: Optional[str] = None
    hq_country: Optional[str] = None
    sector: str
    subsector: Optional[str] = None
    relevance_score: float
    evidence_score: float
    is_pinned: bool
    manual_priority: Optional[int] = None
    review_status: str
    discovered_by: str
    verification_status: str
    exec_search_enabled: bool
    computed_score: float
    score_components: Dict[str, float]
    why_included: List[ProspectSignalEvidence] = []


class CompanyResearchRunSummary(BaseModel):
    """Summary schema for research run with prospect count."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    role_mandate_id: UUID
    status: str
    sector: str
    region_scope: Optional[List[str]] = None
    summary: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    prospect_count: Optional[int] = 0


class CompanyResearchJobRead(TenantScopedRead):
    """Schema for viewing company research jobs."""

    run_id: UUID
    job_type: str
    status: str
    attempt_count: int
    max_attempts: int
    next_retry_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    cancel_requested: bool
    last_error: Optional[str] = None


# ============================================================================
# Source Document Schemas
# ============================================================================

class SourceDocumentCreate(BaseModel):
    """Schema for creating a new source document."""
    
    company_research_run_id: UUID
    source_type: str = Field(..., max_length=50)  # url|pdf|text
    title: Optional[str] = Field(None, max_length=500)
    file_name: Optional[str] = Field(None, max_length=255)
    original_url: Optional[str] = None
    url: Optional[str] = None
    url_normalized: Optional[str] = None
    canonical_final_url: Optional[str] = None
    canonical_source_id: Optional[UUID] = None
    content_text: Optional[str] = None
    content_bytes: Optional[bytes] = None
    content_hash: Optional[str] = Field(None, max_length=64)
    content_size: Optional[int] = Field(None, ge=0)
    mime_type: Optional[str] = Field(None, max_length=100)
    meta: dict[str, Any] = Field(default_factory=dict)
    max_attempts: Optional[int] = Field(default=3, ge=1, le=10)


class SourceDocumentUpdate(BaseModel):
    """Schema for updating a source document."""
    
    content_text: Optional[str] = None
    content_hash: Optional[str] = Field(None, max_length=64)
    original_url: Optional[str] = None
    canonical_final_url: Optional[str] = None
    canonical_source_id: Optional[UUID] = None
    status: Optional[str] = Field(None, max_length=50)
    error_message: Optional[str] = None
    last_error: Optional[str] = None
    attempt_count: Optional[int] = None
    max_attempts: Optional[int] = Field(None, ge=1, le=10)
    next_retry_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    meta: Optional[dict[str, Any]] = None
    title: Optional[str] = Field(None, max_length=500)
    file_name: Optional[str] = Field(None, max_length=255)
    url_normalized: Optional[str] = None
    content_bytes: Optional[bytes] = None
    content_size: Optional[int] = Field(None, ge=0)
    mime_type: Optional[str] = Field(None, max_length=100)
    http_status_code: Optional[int] = None
    http_headers: Optional[Dict[str, Any]] = None
    http_error_message: Optional[str] = None
    http_final_url: Optional[str] = None


class SourceDocumentRead(TenantScopedRead):
    """Schema for reading source document data."""
    
    company_research_run_id: UUID
    source_type: str
    title: Optional[str] = None
    original_url: Optional[str] = None
    url: Optional[str] = None
    url_normalized: Optional[str] = None
    canonical_final_url: Optional[str] = None
    canonical_source_id: Optional[UUID] = None
    file_name: Optional[str] = None
    content_text: Optional[str] = None
    content_hash: Optional[str] = None
    content_size: Optional[int] = None
    mime_type: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    last_error: Optional[str] = None
    attempt_count: int
    max_attempts: int
    next_retry_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    http_status_code: Optional[int] = None
    http_headers: Optional[Dict[str, Any]] = None
    http_error_message: Optional[str] = None
    http_final_url: Optional[str] = None


# ============================================================================
# Research Event Schemas
# ============================================================================

class ResearchEventCreate(BaseModel):
    """Schema for creating a new research event."""
    
    company_research_run_id: UUID
    event_type: str = Field(..., max_length=50)  # fetch|extract|dedupe|enrich
    status: str = Field(..., max_length=50)  # ok|failed
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class ResearchEventRead(TenantScopedRead):
    """Schema for reading research event data."""
    
    company_research_run_id: UUID
    event_type: str
    status: str
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


# ============================================================================
# Entity Resolution Schemas
# ============================================================================

class ResolvedEntityRead(TenantScopedRead):
    """Schema for reading resolved canonical entities."""

    company_research_run_id: UUID
    entity_type: str
    canonical_entity_id: UUID
    match_keys: Dict[str, Any]
    reason_codes: List[str]
    evidence_source_document_ids: List[str]
    resolution_hash: str


class EntityMergeLinkRead(TenantScopedRead):
    """Schema for reading merge links between duplicates and canonicals."""

    company_research_run_id: UUID
    entity_type: str
    resolved_entity_id: UUID
    canonical_entity_id: UUID
    duplicate_entity_id: UUID
    match_keys: Dict[str, Any]
    reason_codes: List[str]
    evidence_source_document_ids: List[str]
    resolution_hash: str


# ============================================================================
# Canonical People Schemas (Stage 6.2)
# ============================================================================

class CanonicalPersonEmailRead(TenantScopedRead):
    canonical_person_id: UUID
    email_normalized: str


class CanonicalPersonLinkRead(TenantScopedRead):
    canonical_person_id: UUID
    person_entity_id: UUID
    match_rule: str
    evidence_source_document_id: UUID
    evidence_company_research_run_id: Optional[UUID] = None


class CanonicalPersonRead(TenantScopedRead):
    canonical_full_name: Optional[str] = None
    primary_email: Optional[str] = None
    primary_linkedin_url: Optional[str] = None
    emails: List[CanonicalPersonEmailRead] = Field(default_factory=list)
    links: List[CanonicalPersonLinkRead] = Field(default_factory=list)


class CanonicalPersonListItem(TenantScopedRead):
    canonical_full_name: Optional[str] = None
    primary_email: Optional[str] = None
    primary_linkedin_url: Optional[str] = None
    linked_entities_count: int = 0


# ============================================================================
# Canonical Company Schemas (Stage 6.3)
# ============================================================================

class CanonicalCompanyDomainRead(TenantScopedRead):
    canonical_company_id: UUID
    domain_normalized: str


class CanonicalCompanyLinkRead(TenantScopedRead):
    canonical_company_id: UUID
    company_entity_id: UUID
    match_rule: str
    evidence_source_document_id: UUID
    evidence_company_research_run_id: Optional[UUID] = None


class CanonicalCompanyRead(TenantScopedRead):
    canonical_name: Optional[str] = None
    primary_domain: Optional[str] = None
    country_code: Optional[str] = None
    domains: List[CanonicalCompanyDomainRead] = Field(default_factory=list)
    links: List[CanonicalCompanyLinkRead] = Field(default_factory=list)


class CanonicalCompanyListItem(TenantScopedRead):
    canonical_name: Optional[str] = None
    primary_domain: Optional[str] = None
    country_code: Optional[str] = None
    linked_entities_count: int = 0

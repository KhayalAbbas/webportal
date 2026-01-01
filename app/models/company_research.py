"""
Company Research models.

Models for company discovery and agentic sourcing engine.
Supports company-level research for mandates with discovery runs,
prospects, evidence tracking, and metrics collection.
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, Integer, Numeric, Boolean, DateTime, ForeignKey, Index, Enum as SQLEnum, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.role import Role
    from app.models.user import User
    from app.models.company import Company


class CompanyResearchRun(TenantScopedModel):
    """
    Company research run - represents one company discovery exercise for a mandate.
    
    Each run is scoped to a role/mandate and has configuration for
    ranking, enrichment, and filtering criteria.
    """
    
    __tablename__ = "company_research_runs"
    
    # Foreign key to role (mandate)
    role_mandate_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id"),
        nullable=False,
        index=True,
    )
    
    # Basic info
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="planned",
        index=True,
    )  # planned, running, completed, failed, cancelled
    
    # Research scope
    sector: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    region_scope: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )  # e.g. ["IN"] or ["AE","SA","QA","OM","KW","BH"]
    
    # Configuration for ranking and enrichment
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Ranking specification - stores user's preferred ranking/sorting method
    rank_spec: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{}',
    )  # e.g. {"sort_mode": "metric", "metric_key": "total_assets", "direction": "desc"}
    
    # Results summary
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Audit fields
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id"),
        nullable=True,
    )
    
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationships
    prospects: Mapped[List["CompanyProspect"]] = relationship(
        "CompanyProspect",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )
    
    source_documents: Mapped[List["ResearchSourceDocument"]] = relationship(
        "ResearchSourceDocument",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )
    
    research_events: Mapped[List["CompanyResearchEvent"]] = relationship(
        "CompanyResearchEvent",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )
    
    metrics: Mapped[List["CompanyMetric"]] = relationship(
        "CompanyMetric",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )

    jobs: Mapped[List["CompanyResearchJob"]] = relationship(
        "CompanyResearchJob",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )

    run_plan: Mapped[Optional["CompanyResearchRunPlan"]] = relationship(
        "CompanyResearchRunPlan",
        back_populates="research_run",
        uselist=False,
        cascade="all, delete-orphan",
    )

    run_steps: Mapped[List["CompanyResearchRunStep"]] = relationship(
        "CompanyResearchRunStep",
        back_populates="research_run",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_company_research_runs_role_mandate_id", "role_mandate_id"),
        Index("ix_company_research_runs_status", "status"),
    )


class CompanyProspect(TenantScopedModel):
    """
    Company prospect - represents one potential relevant company for a mandate.
    
    Stores company information, AI scoring, manual overrides, and status tracking.
    """
    
    __tablename__ = "company_prospects"
    
    # Foreign keys
    company_research_run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id"),
        nullable=False,
        index=True,
    )
    
    role_mandate_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id"),
        nullable=False,
        index=True,
    )  # Denormalized for easy querying
    
    # Company identification
    name_raw: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    
    name_normalized: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
    )  # Canonical cleaned name for deduplication
    
    website_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Location
    hq_country: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
    )  # ISO country code
    
    hq_city: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    
    # Sector classification
    sector: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    subsector: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Size indicators
    employees_band: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g. "<50", "50-200", "200-1000", "1000-5000", "5000+"
    
    revenue_band_usd: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g. "<50m", "50-200m", "200-500m", "500m-1b", "1b+"
    
    # Geographic scope
    countries_of_operation: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )  # Array of ISO country codes
    
    # Description
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Data quality
    data_confidence: Mapped[float] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=0.0,
    )  # 0-1 overall confidence in enrichment data
    
    # AI scoring (DO NOT override manually)
    relevance_score: Mapped[float] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=0.0,
        index=True,
    )  # 0-1 how relevant to mandate
    
    evidence_score: Mapped[float] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=0.0,
    )  # 0-1 strength of evidence
    
    # Phase 2: AI Proposal fields
    ai_rank: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )  # AI-assigned ranking (1=best)
    
    ai_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )  # AI relevance score 0.0-1.0
    
    # Manual override fields (NEVER touched by AI)
    manual_priority: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )  # 1 = highest priority
    
    manual_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )  # Pinned entries always at top
    
    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="new",
        index=True,
    )  # new, approved, rejected, duplicate, converted_to_company
    
    approved_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id"),
        nullable=True,
    )
    
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Link to normalized company if converted
    normalized_company_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company.id"),
        nullable=True,
    )
    
    # Relationships
    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="prospects",
    )
    
    evidence: Mapped[List["CompanyProspectEvidence"]] = relationship(
        "CompanyProspectEvidence",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    
    metrics: Mapped[List["CompanyProspectMetric"]] = relationship(
        "CompanyProspectMetric",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    
    ai_metrics: Mapped[List["CompanyMetric"]] = relationship(
        "CompanyMetric",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    
    aliases: Mapped[List["CompanyAlias"]] = relationship(
        "CompanyAlias",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_company_prospects_role_mandate_id", "role_mandate_id"),
        Index("ix_company_prospects_run_id", "company_research_run_id"),
        Index("ix_company_prospects_status", "status"),
        Index("ix_company_prospects_name_normalized", "name_normalized"),
        Index("ix_company_prospects_relevance_score", "relevance_score"),
        Index("ix_company_prospects_manual_priority", "manual_priority"),
        Index("ix_company_prospects_is_pinned", "is_pinned"),
    )


class CompanyProspectEvidence(TenantScopedModel):
    """
    Company prospect evidence - stores where and how we found each company.
    
    Multiple evidence records can exist per company prospect, tracking
    different sources and discovery methods.
    """
    
    __tablename__ = "company_prospect_evidence"
    
    # Foreign key to prospect
    company_prospect_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_prospects.id"),
        nullable=False,
        index=True,
    )
    
    # Source classification
    source_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )  # ranking_list, association_directory, regulatory_register, web_list, etc.
    
    source_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )  # e.g. "RBI NBFC list 2024"
    
    source_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # List/ranking specific
    list_name: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    list_rank_position: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )  # Position in ranking list
    
    # Search context
    search_query_used: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Evidence quality
    evidence_weight: Mapped[float] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=0.5,
    )  # 0-1 how much this evidence counts
    
    # Raw data
    raw_snippet: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )  # Where company name appeared
    
    # Linkage to source documents (added in Phase 3.5)
    source_document_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    source_content_hash: Mapped[Optional[str]] = mapped_column(
        String(),
        nullable=True,
        index=True,
    )  # Hash of the source document content for quick reference
    
    # Relationship
    prospect: Mapped["CompanyProspect"] = relationship(
        "CompanyProspect",
        back_populates="evidence",
    )
    
    source_document: Mapped[Optional["ResearchSourceDocument"]] = relationship(
        "ResearchSourceDocument",
        foreign_keys=[source_document_id],
    )
    
    __table_args__ = (
        Index("ix_company_prospect_evidence_prospect_id", "company_prospect_id"),
        Index("ix_company_prospect_evidence_source_type", "source_type"),
    )


class CompanyProspectMetric(TenantScopedModel):
    """
    Company prospect metric - stores numeric metrics per company.
    
    Tracks financial and operational metrics like assets, revenue, employees,
    with support for multiple currencies and year-over-year data.
    """
    
    __tablename__ = "company_prospect_metrics"
    
    # Foreign key to prospect
    company_prospect_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_prospects.id"),
        nullable=False,
        index=True,
    )
    
    # Metric identification
    metric_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )  # total_assets, revenue, aum, employees, market_cap, passengers, etc.
    
    # Value in original units
    value_raw: Mapped[Optional[float]] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )
    
    currency: Mapped[Optional[str]] = mapped_column(
        String(3),
        nullable=True,
    )  # ISO currency code (INR, USD, etc.) - null for unitless metrics
    
    # Converted USD value for financial metrics
    value_usd: Mapped[Optional[float]] = mapped_column(
        Numeric(20, 2),
        nullable=True,
    )
    
    # Time context
    as_of_year: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    # Source tracking
    source_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )  # regulator, annual_report, finance_site, etc.
    
    source_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Data quality
    data_confidence: Mapped[float] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=0.5,
    )  # 0-1 confidence in this metric
    
    # Relationship
    prospect: Mapped["CompanyProspect"] = relationship(
        "CompanyProspect",
        back_populates="metrics",
    )
    
    __table_args__ = (
        Index("ix_company_prospect_metrics_prospect_id", "company_prospect_id"),
        Index("ix_company_prospect_metrics_type_year", "metric_type", "as_of_year"),
    )


class ResearchSourceDocument(TenantScopedModel):
    """
    Source document for company research.
    
    Stores raw sources (URLs, PDFs, text) that are processed to extract
    company prospects. Tracks processing status and maintains audit trail.
    """
    
    __tablename__ = "source_documents"
    
    # Foreign key to research run
    company_research_run_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    # Source type
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # enum: url|pdf|text
    
    # Source metadata
    title: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    # Content
    content_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )  # Extracted text content
    
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )  # SHA256 hash for deduplication

    meta: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{}',
    )
    
    # Phase 2: AI Proposal fields
    provider: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )  # AI provider or data source name
    
    snippet: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )  # Evidence snippet
    
    # Processing status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="new",
        index=True,
    )  # enum: new|fetched|processed|failed
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Timestamps
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationship
    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="source_documents",
    )
    
    __table_args__ = (
        Index("ix_source_documents_run_id", "company_research_run_id"),
        Index("ix_source_documents_status", "status"),
        Index("ix_source_documents_hash", "content_hash"),
        # Note: Unique constraint on (tenant_id, content_hash) would be beneficial but skipped due to existing duplicates
    )


class CompanyResearchEvent(TenantScopedModel):
    """
    Audit log for research processing events.
    
    Tracks all processing steps (fetch, extract, dedupe, enrich) with
    input/output data and error details for debugging and monitoring.
    """
    
    __tablename__ = "research_events"
    
    # Foreign key to research run
    company_research_run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Event classification
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # enum: fetch|extract|dedupe|enrich
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # enum: ok|failed
    
    # Event data
    input_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    output_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationship
    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="research_events",
    )
    
    __table_args__ = (
        Index("ix_research_events_run_id", "company_research_run_id"),
        Index("ix_research_events_type", "event_type"),
        Index("ix_research_events_status", "status"),
        Index("ix_research_events_created", "created_at"),
    )


class CompanyResearchJob(TenantScopedModel):
    """
    Durable queue entry for company research runs.
    """

    __tablename__ = "company_research_jobs"

    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    job_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="company_research_run",
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        index=True,
    )  # queued|running|succeeded|failed|cancelled

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )

    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_by: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )

    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="jobs",
    )

    __table_args__ = (
        Index("ix_company_research_jobs_status_next_retry", "tenant_id", "status", "next_retry_at"),
        Index("ix_company_research_jobs_tenant_run", "tenant_id", "run_id"),
        Index(
            "uq_company_research_jobs_active",
            "tenant_id",
            "run_id",
            "job_type",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )


class CompanyResearchRunPlan(TenantScopedModel):
    """Versioned research plan for a run."""

    __tablename__ = "company_research_run_plans"

    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="run_plan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", name="uq_company_research_run_plans_run"),
    )


class CompanyResearchRunStep(TenantScopedModel):
    """Deterministic steps for executing a research run."""

    __tablename__ = "company_research_run_steps"

    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    step_key: Mapped[str] = mapped_column(Text, nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="run_steps",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "step_key", name="uq_company_research_run_steps_key"),
        Index("ix_company_research_run_steps_order", "tenant_id", "run_id", "step_order"),
        Index("ix_company_research_run_steps_status_retry", "tenant_id", "status", "next_retry_at"),
    )


class CompanyMetric(TenantScopedModel):
    """
    Company metric - stores quantitative/qualitative metrics for companies.
    
    Used in Phase 2 AI proposal ingestion to store metrics like
    total_assets, revenue, employee_count, etc.
    """
    
    __tablename__ = "company_metrics"
    
    # Foreign keys
    company_research_run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_research_runs.id"),
        nullable=False,
        index=True,
    )
    
    company_prospect_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_prospects.id"),
        nullable=False,
        index=True,
    )
    
    # Metric identification
    metric_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )  # e.g. 'total_assets', 'revenue', 'employee_count'
    
    # Value type - determines which value_* column is used
    value_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # 'number', 'text', 'bool', 'json'
    
    # Metric value (exactly one of these will be populated based on value_type)
    value_number: Mapped[Optional[float]] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )
    
    value_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    value_bool: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
    )
    
    value_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Additional metadata for values
    value_currency: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )  # ISO currency code (USD, EUR, etc.) - for number types
    
    unit: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # Unit of measurement (kg, aircraft, employees, etc.) - for number types
    
    # Metadata
    as_of_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    confidence: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 2),
        nullable=True,
    )  # 0.0 to 1.0
    
    source_document_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_documents.id"),
        nullable=True,
    )
    
    # Relationships
    research_run: Mapped["CompanyResearchRun"] = relationship(
        "CompanyResearchRun",
        back_populates="metrics",
    )
    
    prospect: Mapped["CompanyProspect"] = relationship(
        "CompanyProspect",
        back_populates="ai_metrics",
    )
    
    source_document: Mapped[Optional["ResearchSourceDocument"]] = relationship(
        "ResearchSourceDocument",
    )
    
    __table_args__ = (
        Index("ix_company_metrics_tenant_id", "tenant_id"),
        Index("ix_company_metrics_run_id", "company_research_run_id"),
        Index("ix_company_metrics_prospect_id", "company_prospect_id"),
        Index("ix_company_metrics_key", "metric_key"),
    )


class CompanyAlias(TenantScopedModel):
    """
    Company alias - stores alternative names for companies.
    
    Used to track legal names, trade names, former names, local variations, etc.
    Helps with deduplication and matching in Phase 2 AI ingestion.
    """
    
    __tablename__ = "company_aliases"
    
    # Foreign key
    company_prospect_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_prospects.id"),
        nullable=False,
        index=True,
    )
    
    # Alias details
    alias_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
    )
    
    alias_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # 'legal', 'trade', 'former', 'local', 'abbreviation'
    
    source_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )  # Where this alias came from
    
    confidence: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 2),
        nullable=True,
    )  # 0.0 to 1.0
    
    # Relationship
    prospect: Mapped["CompanyProspect"] = relationship(
        "CompanyProspect",
        back_populates="aliases",
    )
    
    __table_args__ = (
        Index("ix_company_aliases_tenant_id", "tenant_id"),
        Index("ix_company_aliases_prospect_id", "company_prospect_id"),
        Index("ix_company_aliases_name", "alias_name"),
    )

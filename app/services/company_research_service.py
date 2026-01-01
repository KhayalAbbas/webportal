"""
Company Research Service - business logic layer.

Provides validation and orchestration for company discovery operations.
Phase 1: Backend structures only, no external AI/crawling yet.
"""

from typing import List, Optional
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.company_research_repo import CompanyResearchRepository
from app.models.company_research import (
    CompanyResearchRun,
    CompanyProspect,
    CompanyProspectEvidence,
    CompanyProspectMetric,
    ResearchSourceDocument,
    CompanyResearchEvent,
    CompanyResearchJob,
)
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyResearchRunUpdate,
    CompanyProspectCreate,
    CompanyProspectUpdate,
    CompanyProspectUpdateManual,
    CompanyProspectEvidenceCreate,
    CompanyProspectMetricCreate,
    SourceDocumentCreate,
    SourceDocumentUpdate,
    ResearchEventCreate,
)


class CompanyResearchService:
    """Service layer for company research operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)
    
    # ========================================================================
    # Company Research Run Operations
    # ========================================================================
    
    async def create_research_run(
        self,
        tenant_id: str,
        data: CompanyResearchRunCreate,
        created_by_user_id: Optional[UUID] = None,
    ) -> CompanyResearchRun:
        """
        Create a new company research run.
        
        Validates config structure and creates the run record.
        """
        # Validate config structure if provided
        if data.config:
            self._validate_research_config(data.config)
        
        return await self.repo.create_company_research_run(
            tenant_id=tenant_id,
            data=data,
            created_by_user_id=created_by_user_id,
        )
    
    async def get_research_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> Optional[CompanyResearchRun]:
        """Get a research run by ID."""
        return await self.repo.get_company_research_run(tenant_id, run_id)
    
    async def list_research_runs_for_role(
        self,
        tenant_id: str,
        role_mandate_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyResearchRun]:
        """List all research runs for a role/mandate."""
        return await self.repo.list_company_research_runs_for_role(
            tenant_id=tenant_id,
            role_mandate_id=role_mandate_id,
            limit=limit,
            offset=offset,
        )

    async def list_research_runs(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyResearchRun]:
        return await self.repo.list_company_research_runs(
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    
    async def update_research_run(
        self,
        tenant_id: str,
        run_id: UUID,
        data: CompanyResearchRunUpdate,
    ) -> Optional[CompanyResearchRun]:
        """Update a research run."""
        return await self.repo.update_company_research_run(
            tenant_id=tenant_id,
            run_id=run_id,
            data=data,
        )

    async def start_run(self, tenant_id: str, run_id: UUID) -> CompanyResearchJob:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        job = await self.repo.enqueue_run_job(tenant_id=tenant_id, run_id=run_id)
        await self.repo.set_run_status(
            tenant_id=tenant_id,
            run_id=run_id,
            status="queued",
            last_error=None,
            started_at=None,
        )
        await self.db.flush()
        return job

    async def retry_run(self, tenant_id: str, run_id: UUID) -> CompanyResearchJob:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        job = await self.repo.enqueue_run_job(tenant_id=tenant_id, run_id=run_id)
        await self.repo.set_run_status(
            tenant_id=tenant_id,
            run_id=run_id,
            status="queued",
            last_error=None,
            started_at=None,
            finished_at=None,
        )
        await self.db.flush()
        return job

    async def cancel_run(self, tenant_id: str, run_id: UUID) -> str:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            return "not_found"

        if run.status in {"succeeded", "failed", "cancelled"}:
            return "noop_terminal"

        requested = await self.repo.request_cancel_job(tenant_id=tenant_id, run_id=run_id)
        if requested:
            await self.repo.set_run_status(tenant_id, run_id, status="cancel_requested")
            await self.db.flush()
            return "requested"

        await self.db.flush()
        return "no_active_job"
    
    # ========================================================================
    # Company Prospect Operations
    # ========================================================================
    
    async def create_prospect(
        self,
        tenant_id: str,
        data: CompanyProspectCreate,
    ) -> CompanyProspect:
        """Create a new company prospect."""
        return await self.repo.create_company_prospect(tenant_id, data)
    
    async def get_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
    ) -> Optional[CompanyProspect]:
        """Get a company prospect by ID."""
        return await self.repo.get_company_prospect(tenant_id, prospect_id)
    
    async def list_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        status: Optional[str] = None,
        min_relevance_score: Optional[float] = None,
        order_by: str = "ai",
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyProspect]:
        """
        List prospects for a research run with filtering and ordering.
        
        Args:
            tenant_id: Tenant ID
            run_id: Research run ID
            status: Optional status filter (new, approved, rejected, duplicate, converted)
            min_relevance_score: Minimum AI relevance score (0.0 - 1.0)
            order_by: Ordering mode - "ai" (relevance), "manual" (user priority)
            limit: Maximum results
            offset: Results offset
        """
        return await self.repo.list_company_prospects_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            status=status,
            min_relevance_score=min_relevance_score,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    
    async def list_prospects_for_run_with_evidence(
        self,
        tenant_id: str,
        run_id: UUID,
        status: Optional[str] = None,
        min_relevance_score: Optional[float] = None,
        order_by: str = "ai",
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyProspect]:
        """
        List prospects for a research run with evidence and source documents.
        
        Uses efficient joins to avoid N+1 queries.
        """
        return await self.repo.list_prospects_for_run_with_evidence(
            tenant_id=tenant_id,
            run_id=run_id,
            status=status,
            min_relevance_score=min_relevance_score,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    
    async def update_prospect_manual_fields(
        self,
        tenant_id: str,
        prospect_id: UUID,
        data: CompanyProspectUpdateManual,
    ) -> Optional[CompanyProspect]:
        """
        Update manual override fields for a prospect.
        
        This method ensures AI-calculated fields are never touched by user input.
        Only manual_priority, manual_notes, is_pinned, and status are updated.
        """
        return await self.repo.update_company_prospect_manual_fields(
            tenant_id=tenant_id,
            prospect_id=prospect_id,
            data=data,
        )
    
    async def count_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> int:
        """Count total prospects for a research run."""
        return await self.repo.count_prospects_for_run(tenant_id, run_id)

    async def list_events_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        limit: int = 100,
    ) -> List[CompanyResearchEvent]:
        return await self.repo.list_research_events_for_run(tenant_id, run_id, limit)

    # ====================================================================
    # Job Queue Operations
    # ====================================================================

    async def claim_next_job(self, worker_id: str) -> Optional[CompanyResearchJob]:
        return await self.repo.claim_next_job(worker_id)

    async def mark_job_running(self, job_id: UUID, worker_id: str) -> Optional[CompanyResearchJob]:
        return await self.repo.mark_job_running(job_id, worker_id)

    async def mark_job_succeeded(self, job_id: UUID) -> Optional[CompanyResearchJob]:
        return await self.repo.mark_job_succeeded(job_id)

    async def mark_job_failed(self, job_id: UUID, last_error: str, backoff_seconds: int = 30) -> Optional[CompanyResearchJob]:
        return await self.repo.mark_job_failed(job_id, last_error, backoff_seconds)

    async def mark_job_cancelled(self, job_id: UUID, last_error: Optional[str] = None) -> Optional[CompanyResearchJob]:
        return await self.repo.mark_job_cancelled(job_id, last_error)

    async def append_event(
        self,
        tenant_id: str,
        run_id: UUID,
        event_type: str,
        message: str,
        meta_json: Optional[dict] = None,
        status: str = "ok",
    ) -> CompanyResearchEvent:
        return await self.repo.append_research_event(tenant_id, run_id, event_type, message, meta_json, status)
    
    # ========================================================================
    # Evidence Operations
    # ========================================================================
    
    async def add_evidence_to_prospect(
        self,
        tenant_id: str,
        data: CompanyProspectEvidenceCreate,
    ) -> CompanyProspectEvidence:
        """Add evidence to a company prospect."""
        return await self.repo.create_company_prospect_evidence(tenant_id, data)
    
    async def list_evidence_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
    ) -> List[CompanyProspectEvidence]:
        """List all evidence for a specific prospect."""
        return await self.repo.list_evidence_for_prospect(tenant_id, prospect_id)
    
    # ========================================================================
    # Metric Operations
    # ========================================================================
    
    async def add_metric_to_prospect(
        self,
        tenant_id: str,
        data: CompanyProspectMetricCreate,
    ) -> CompanyProspectMetric:
        """Add a metric to a company prospect."""
        return await self.repo.create_company_prospect_metric(tenant_id, data)
    
    async def list_metrics_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
        metric_type: Optional[str] = None,
    ) -> List[CompanyProspectMetric]:
        """List all metrics for a specific prospect."""
        return await self.repo.list_metrics_for_prospect(
            tenant_id=tenant_id,
            prospect_id=prospect_id,
            metric_type=metric_type,
        )
    
    async def get_latest_metric_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
        metric_type: str,
    ) -> Optional[CompanyProspectMetric]:
        """Get the most recent metric of a specific type for a prospect."""
        return await self.repo.get_latest_metric_for_prospect(
            tenant_id=tenant_id,
            prospect_id=prospect_id,
            metric_type=metric_type,
        )
    
    # ========================================================================
    # Validation Helpers
    # ========================================================================
    
    def _validate_research_config(self, config: dict) -> None:
        """
        Validate research run config structure.
        
        Expected structure:
        {
            "ranking": {
                "primary_metric": "total_assets",
                "currency": "USD",
                "as_of_year": 2024,
                "direction": "desc"
            },
            "enrichment": {
                "metrics_to_collect": ["total_assets", "revenue", "employees"]
            }
        }
        """
        if not isinstance(config, dict):
            raise ValueError("Config must be a dictionary")
        
        # Validate ranking config
        if "ranking" in config:
            ranking = config["ranking"]
            if not isinstance(ranking, dict):
                raise ValueError("ranking must be a dictionary")
            
            # Validate primary_metric
            if "primary_metric" in ranking:
                valid_metrics = [
                    "total_assets", "revenue", "employees", "net_income",
                    "market_cap", "equity", "debt"
                ]
                if ranking["primary_metric"] not in valid_metrics:
                    raise ValueError(f"primary_metric must be one of: {valid_metrics}")
            
            # Validate direction
            if "direction" in ranking:
                if ranking["direction"] not in ["asc", "desc"]:
                    raise ValueError("direction must be 'asc' or 'desc'")
        
        # Validate enrichment config
        if "enrichment" in config:
            enrichment = config["enrichment"]
            if not isinstance(enrichment, dict):
                raise ValueError("enrichment must be a dictionary")
            
            if "metrics_to_collect" in enrichment:
                if not isinstance(enrichment["metrics_to_collect"], list):
                    raise ValueError("metrics_to_collect must be a list")
    
    # ========================================================================
    # Source Document Operations
    # ========================================================================
    
    async def add_source(
        self,
        tenant_id: str,
        data: SourceDocumentCreate,
    ) -> ResearchSourceDocument:
        """Add a new source document to a research run."""
        return await self.repo.create_source_document(tenant_id, data)
    
    async def get_source(
        self,
        tenant_id: str,
        source_id: UUID,
    ) -> Optional[ResearchSourceDocument]:
        """Get a source document by ID."""
        return await self.repo.get_source_document(tenant_id, source_id)
    
    async def list_sources_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ResearchSourceDocument]:
        """List all sources for a research run."""
        return await self.repo.list_source_documents_for_run(tenant_id, run_id)
    
    async def update_source(
        self,
        tenant_id: str,
        source_id: UUID,
        data: SourceDocumentUpdate,
    ) -> Optional[ResearchSourceDocument]:
        """Update a source document."""
        return await self.repo.update_source_document(tenant_id, source_id, data)
    
    # ========================================================================
    # Research Event Operations
    # ========================================================================
    
    async def list_events_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        limit: int = 100,
    ) -> List[CompanyResearchEvent]:
        """List research events (audit log) for a run."""
        return await self.repo.list_research_events_for_run(tenant_id, run_id, limit)

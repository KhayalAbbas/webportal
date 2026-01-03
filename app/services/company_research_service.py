"""
Company Research Service - business logic layer.

Provides validation and orchestration for company discovery operations.
Phase 1: Backend structures only, no external AI/crawling yet.
"""

import hashlib
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID
from urllib.parse import urlparse, urlunparse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.repositories.company_research_repo import CompanyResearchRepository
from app.models.company_research import (
    CompanyResearchRun,
    CompanyProspect,
    CompanyProspectEvidence,
    CompanyProspectMetric,
    ResearchSourceDocument,
    CompanyResearchEvent,
    CompanyResearchJob,
    CompanyResearchRunPlan,
    CompanyResearchRunStep,
)
from app.services.ai_proposal_service import AIProposalService
from app.schemas.ai_proposal import AIProposal
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

    async def ensure_sources_unlocked(self, tenant_id: str, run_id: UUID) -> CompanyResearchRun:
        """Raise if the run/plan is locked for source mutations."""
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        plan = await self.get_run_plan(tenant_id, run_id)
        if plan and plan.locked_at:
            raise ValueError("plan_locked")

        if run.status not in {"planned", "active"}:
            raise ValueError("run_locked")

        return run
    
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

    # ====================================================================
    # Plan & Step Management
    # ====================================================================

    async def build_deterministic_plan_for_run(self, tenant_id: str, run_id: UUID) -> dict:
        sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        has_url_sources = any(
            src.source_type == "url" or (src.meta or {}).get("kind") == "url"
            for src in sources
        )
        has_list_sources = any(
            src.source_type in {"manual_list", "list"} or (src.meta or {}).get("kind") == "list"
            for src in sources
        )
        has_proposal_sources = any(
            src.source_type == "ai_proposal" or (src.meta or {}).get("kind") == "proposal"
            for src in sources
        )

        steps = [
            {
                "step_key": "fetch_url_sources",
                "step_order": 5,
                "rationale": "Fetch URL sources before extraction",
                "enabled": has_url_sources,
                "max_attempts": 5,
            },
            {
                "step_key": "process_sources",
                "step_order": 10,
                "rationale": "Process queued research sources",
                "enabled": True,
            },
            {
                "step_key": "ingest_lists",
                "step_order": 20,
                "rationale": "Ingest manual list sources if present",
                "enabled": has_list_sources,
            },
            {
                "step_key": "ingest_proposal",
                "step_order": 30,
                "rationale": "Ingest AI proposals if provided",
                "enabled": has_proposal_sources,
            },
            {
                "step_key": "finalize",
                "step_order": 99,
                "rationale": "Mark run complete once all steps succeed",
                "enabled": True,
            },
        ]

        return {
            "version": 1,
            "run_id": str(run_id),
            "steps": steps,
        }

    async def ensure_plan_and_steps(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> tuple[CompanyResearchRunPlan, List[CompanyResearchRunStep]]:
        plan_json = await self.build_deterministic_plan_for_run(tenant_id, run_id)
        plan = await self.repo.create_plan_if_missing(
            tenant_id=tenant_id,
            run_id=run_id,
            plan_json=plan_json,
            version=plan_json.get("version", 1),
        )

        enabled_steps = []
        for step in plan_json.get("steps", []):
            if step.get("enabled", True):
                max_attempts = step.get("max_attempts", 2)
                enabled_steps.append(
                    {
                        "step_key": step["step_key"],
                        "step_order": step["step_order"],
                        "status": "pending",
                        "max_attempts": max_attempts,
                        "input_json": {"rationale": step.get("rationale")},
                    }
                )

        steps = await self.repo.upsert_steps(tenant_id, run_id, enabled_steps)
        return plan, steps

    async def lock_plan_on_start(self, tenant_id: str, run_id: UUID) -> Optional[CompanyResearchRunPlan]:
        return await self.repo.lock_plan(tenant_id, run_id)

    async def get_run_plan(self, tenant_id: str, run_id: UUID) -> Optional[CompanyResearchRunPlan]:
        return await self.repo.get_run_plan(tenant_id, run_id)

    async def list_run_steps(self, tenant_id: str, run_id: UUID) -> List[CompanyResearchRunStep]:
        return await self.repo.list_steps(tenant_id, run_id)

    async def start_run(self, tenant_id: str, run_id: UUID) -> CompanyResearchJob:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        await self.ensure_plan_and_steps(tenant_id, run_id)
        await self.lock_plan_on_start(tenant_id, run_id)

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

        await self.ensure_plan_and_steps(tenant_id, run_id)
        await self.lock_plan_on_start(tenant_id, run_id)

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

    @staticmethod
    def _normalize_company_name(name: str) -> str:
        """Normalize company name for canonical identity matching."""
        if not name:
            return ""

        normalized = name.lower().strip()

        while normalized and normalized[-1] in '.,;:':
            normalized = normalized[:-1].strip()

        suffixes = [
            ' ltd', ' llc', ' plc', ' saog', ' sa', ' gmbh', ' ag',
            ' inc', ' corp', ' corporation', ' limited', ' group', ' holdings',
            ' company', ' co',
        ]
        changed = True
        while changed:
            changed = False
            for suffix in suffixes:
                if normalized.endswith(suffix):
                    normalized = normalized[:-len(suffix)].strip()
                    changed = True
                    break
            while normalized and normalized[-1] in '.,;:':
                normalized = normalized[:-1].strip()
                changed = True

        return ' '.join(normalized.split())

    @staticmethod
    def _hash_text(content: Optional[str]) -> Optional[str]:
        if not content:
            return None
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_url_value(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url)
        scheme = (parsed.scheme or "http").lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        normalized = parsed._replace(
            scheme=scheme,
            netloc=netloc,
            path=path.rstrip("/") or "/",
            params="",
            query="",
            fragment="",
        )
        return urlunparse(normalized)
    
    async def add_source(
        self,
        tenant_id: str,
        data: SourceDocumentCreate,
    ) -> ResearchSourceDocument:
        """Add a new source document to a research run."""
        if not data.content_hash:
            if data.content_bytes:
                data.content_hash = hashlib.sha256(data.content_bytes).hexdigest()
            elif data.content_text:
                data.content_hash = self._hash_text(data.content_text)
        if not data.url_normalized and data.url:
            data.url_normalized = self._normalize_url_value(data.url)
        if data.content_bytes is not None and data.content_size is None:
            data.content_size = len(data.content_bytes)
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

    async def fetch_url_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Fetch pending URL sources for a run."""
        extractor = CompanyExtractionService(self.db)
        return await extractor.fetch_url_sources(tenant_id=tenant_id, run_id=run_id)

    # ========================================================================
    # List Ingestion
    # ========================================================================

    async def ingest_list_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Ingest manual list sources into prospects and evidence."""
        sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        pending = [
            s
            for s in sources
            if s.status in {"new", "fetched"}
            and (s.source_type in {"manual_list", "text", "list"} or (s.meta or {}).get("kind") == "list")
        ]

        if not pending:
            return {"skipped": True, "reason": "no_pending_list_sources"}

        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        entries_by_norm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        per_source_stats = []

        for src in pending:
            raw_lines = [line.strip() for line in (src.content_text or "").splitlines() if line.strip()]
            normalized_lines = 0
            for raw in raw_lines:
                norm = self._normalize_company_name(raw)
                if not norm:
                    continue
                normalized_lines += 1
                entries_by_norm[norm].append(
                    {
                        "raw": raw,
                        "normalized": norm,
                        "source_id": src.id,
                        "source_label": src.title or (src.meta or {}).get("source_name") or "manual_list",
                        "source_type": src.source_type,
                    }
                )

            per_source_stats.append(
                {
                    "source_id": str(src.id),
                    "title": src.title,
                    "lines": len(raw_lines),
                    "normalized": normalized_lines,
                }
            )

        if not entries_by_norm:
            for src in pending:
                src.status = "processed"
                meta = dict(src.meta or {})
                meta["ingest_stats"] = {"parsed": 0, "new": 0, "existing": 0}
                src.meta = meta
            await self.db.flush()
            return {
                "processed_sources": len(pending),
                "parsed_total": 0,
                "new": 0,
                "existing": 0,
                "duplicates": 0,
                "sources_detail": per_source_stats,
            }

        # Query existing prospects in bulk
        norm_names = list(entries_by_norm.keys())
        existing_result = await self.db.execute(
            select(CompanyProspect).where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
                CompanyProspect.name_normalized.in_(norm_names),
            )
        )
        existing_map = {p.name_normalized: p for p in existing_result.scalars().all()}

        stats = {
            "parsed_total": sum(len(v) for v in entries_by_norm.values()),
            "unique_normalized": len(entries_by_norm),
            "new": 0,
            "existing": 0,
            "duplicates": 0,
            "processed_sources": len(pending),
        }

        async def insert_manual_evidence(prospect_id: UUID, entry: dict[str, Any]) -> None:
            stmt = (
                insert(CompanyProspectEvidence)
                .values(
                    tenant_id=tenant_id,
                    company_prospect_id=prospect_id,
                    source_type=entry.get("source_type") or "manual_list",
                    source_name=entry.get("source_label") or "manual_list",
                    raw_snippet=entry.get("raw"),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        CompanyProspectEvidence.tenant_id,
                        CompanyProspectEvidence.company_prospect_id,
                        CompanyProspectEvidence.source_type,
                        CompanyProspectEvidence.source_name,
                    ]
                )
            )
            await self.db.execute(stmt)

        for norm_name, entries in entries_by_norm.items():
            prospect = existing_map.get(norm_name)
            if prospect:
                stats["existing"] += 1
            else:
                stats["new"] += 1
                primary_entry = entries[0]
                prospect = CompanyProspect(
                    tenant_id=tenant_id,
                    company_research_run_id=run_id,
                    role_mandate_id=run.role_mandate_id,
                    name_raw=primary_entry["raw"],
                    name_normalized=norm_name,
                    status="new",
                )
                self.db.add(prospect)
                await self.db.flush()
                existing_map[norm_name] = prospect

            sources_seen = set()
            for entry in entries:
                key = (entry.get("source_type"), entry.get("source_label"))
                if key in sources_seen:
                    continue
                await insert_manual_evidence(prospect.id, entry)
                sources_seen.add(key)

            if len(entries) > 1:
                stats["duplicates"] += len(entries) - 1

        for src in pending:
            meta = dict(src.meta or {})
            meta["ingest_stats"] = {
                "parsed": meta.get("ingest_stats", {}).get("parsed", 0) + sum(
                    1 for entries in entries_by_norm.values() for entry in entries if entry["source_id"] == src.id
                ),
                "new": stats["new"],
                "existing": stats["existing"],
            }
            src.meta = meta
            src.status = "processed"
            src.error_message = None

        await self.db.flush()

        return {
            "processed_sources": len(pending),
            "parsed_total": stats["parsed_total"],
            "unique_normalized": stats["unique_normalized"],
            "new": stats["new"],
            "existing": stats["existing"],
            "duplicates": stats["duplicates"],
            "sources_detail": per_source_stats,
        }

    # ========================================================================
    # Proposal Ingestion
    # ========================================================================

    async def ingest_proposal_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Ingest proposal sources queued as source documents."""
        sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        pending = [
            s
            for s in sources
            if s.status in {"new", "fetched"}
            and (s.source_type == "ai_proposal" or (s.meta or {}).get("kind") == "proposal")
        ]

        if not pending:
            return {"skipped": True, "reason": "no_pending_proposal_sources"}

        proposal_service = AIProposalService(self.db)
        tenant_uuid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
        summary = {
            "processed_sources": 0,
            "ingestions_succeeded": 0,
            "ingestions_failed": 0,
            "companies_new": 0,
            "companies_existing": 0,
            "warnings": 0,
            "details": [],
        }

        for src in pending:
            detail = {"source_id": str(src.id), "title": src.title}
            try:
                payload = json.loads(src.content_text or "{}")
                proposal = AIProposal(**payload)
                ingestion_result = await proposal_service.ingest_proposal(
                    tenant_id=tenant_uuid,
                    run_id=run_id,
                    proposal=proposal,
                )
                summary["processed_sources"] += 1
                if ingestion_result.success:
                    summary["ingestions_succeeded"] += 1
                    summary["companies_new"] += ingestion_result.companies_new
                    summary["companies_existing"] += ingestion_result.companies_existing
                    summary["warnings"] += len(ingestion_result.warnings)
                    detail["companies"] = ingestion_result.companies_ingested
                    detail["metrics"] = ingestion_result.metrics_ingested
                    detail["aliases"] = ingestion_result.aliases_ingested
                    detail["warnings"] = ingestion_result.warnings
                    src.status = "processed"
                    src.error_message = None
                else:
                    summary["ingestions_failed"] += 1
                    detail["errors"] = ingestion_result.errors
                    src.status = "failed"
                    src.error_message = "; ".join(ingestion_result.errors[:3])
                src.meta = {**(src.meta or {}), "ingest_detail": detail}
            except Exception as exc:  # noqa: BLE001
                summary["ingestions_failed"] += 1
                detail["errors"] = [str(exc)]
                src.status = "failed"
                src.error_message = str(exc)
                src.meta = {**(src.meta or {}), "ingest_detail": detail}

            summary["details"].append(detail)

        await self.db.flush()
        return summary
    
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

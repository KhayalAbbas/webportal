"""
Company Research Service - business logic layer.

Provides validation and orchestration for company discovery operations.
Phase 1: Backend structures only, no external AI/crawling yet.
"""

import hashlib
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID
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
    ExecutiveProspect,
    ExecutiveProspectEvidence,
)
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.services.ai_proposal_service import AIProposalService
from app.schemas.ai_proposal import AIProposal
from app.schemas.ai_enrichment import AIEnrichmentCreate
from app.schemas.llm_discovery import LlmDiscoveryPayload
from app.schemas.executive_discovery import ExecutiveDiscoveryPayload
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
from app.utils.url_canonicalizer import canonicalize_url


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

        has_llm_sources = any(
            src.source_type == "llm_json" or (src.meta or {}).get("kind") == "llm_json"
            for src in sources
        )
        external_llm_enabled = bool(int(os.getenv("EXTERNAL_LLM_ENABLED", "0") or 0))

        steps = [
            {
                "step_key": "external_llm_company_discovery",
                "step_order": 4,
                "rationale": "Ingest external LLM JSON discovery payloads before fetching URLs",
                "enabled": has_llm_sources or external_llm_enabled,
                "max_attempts": 2,
            },
            {
                "step_key": "fetch_url_sources",
                "step_order": 10,
                "rationale": "Fetch URL sources before extraction",
                "enabled": has_url_sources,
                "max_attempts": 5,
            },
            {
                "step_key": "extract_url_sources",
                "step_order": 15,
                "rationale": "Deterministically extract text + quality flags from fetched sources",
                "enabled": has_url_sources,
                "max_attempts": 3,
            },
            {
                "step_key": "process_sources",
                "step_order": 20,
                "rationale": "Process queued research sources",
                "enabled": True,
            },
            {
                "step_key": "ingest_lists",
                "step_order": 30,
                "rationale": "Ingest manual list sources if present",
                "enabled": has_list_sources,
            },
            {
                "step_key": "ingest_proposal",
                "step_order": 40,
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

    async def list_executives_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ExecutiveProspect]:
        """List executive prospects for a research run."""
        result = await self.db.execute(
            select(ExecutiveProspect).where(
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.company_research_run_id == run_id,
            ).order_by(ExecutiveProspect.created_at.desc())
        )
        return list(result.scalars().all())
    
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
        return canonicalize_url(url)

    @staticmethod
    def _normalize_country_code(country: Optional[str]) -> Optional[str]:
        """Normalize country to a 2-letter code to satisfy column constraints."""
        if not country:
            return None
        normalized = (country or "").strip().upper()
        replacements = {
            "UAE": "AE",
            "KSA": "SA",
            "UK": "GB",
            "GBR": "GB",
            "USA": "US",
        }
        normalized = replacements.get(normalized, normalized)
        if len(normalized) > 2:
            normalized = normalized[:2]
        return normalized or None

    @staticmethod
    def _canonical_json(data: Any) -> str:
        """Return deterministic JSON string for hashing/idempotency."""
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _normalize_person_name(name: Optional[str]) -> str:
        """Normalize person names for matching."""
        if not name:
            return ""
        normalized = name.lower().strip()
        normalized = normalized.replace(".", " ").replace(",", " ")
        normalized = " ".join(normalized.split())
        return normalized

    @staticmethod
    def _merge_discovered_by(existing: Optional[str], incoming: str) -> str:
        """Combine discovery provenance into a compact label."""
        if not existing:
            return incoming
        if existing == incoming or existing == "both":
            return existing
        return "both"
    
    async def add_source(
        self,
        tenant_id: str,
        data: SourceDocumentCreate,
    ) -> ResearchSourceDocument:
        """Add a new source document to a research run."""
        data.meta = data.meta or {}
        if not data.content_hash:
            if data.content_bytes:
                data.content_hash = hashlib.sha256(data.content_bytes).hexdigest()
            elif data.content_text:
                data.content_hash = self._hash_text(data.content_text)
        if not data.url_normalized and data.url:
            data.url_normalized = self._normalize_url_value(data.url)
        if data.url and not data.original_url:
            data.original_url = data.url
        if data.content_bytes is not None and data.content_size is None:
            data.content_size = len(data.content_bytes)
        return await self.repo.create_source_document(tenant_id, data)

    async def ingest_llm_json_payload(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: dict,
        provider: str,
        model_name: Optional[str],
        title: Optional[str],
        purpose: str = "company_discovery",
    ) -> dict:
        """Ingest an external LLM JSON payload into the research run.

        This is idempotent by canonical payload hash. If the same payload is
        posted multiple times, no additional sources, enrichments, prospects,
        or URL sources will be created.
        """

        if purpose != "company_discovery":
            raise ValueError("invalid_purpose")

        parsed = LlmDiscoveryPayload(**payload)
        canonical = self._canonical_json(parsed.canonical_dict())
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        existing_source = await self.repo.find_source_by_hash(tenant_id, run_id, content_hash)
        if existing_source and existing_source.source_type == "llm_json":
            ingest_meta = {
                "companies_new": 0,
                "companies_existing": 0,
                "evidence_created": 0,
                "urls_created": 0,
                "urls_existing": 0,
            }
            return {
                "skipped": True,
                "reason": "duplicate_hash",
                "source_id": str(existing_source.id),
                "ingest_stats": ingest_meta,
            }

        source_meta = {
            "kind": "llm_json",
            "provider": provider,
            "model": model_name,
            "purpose": purpose,
            "schema_version": parsed.schema_version,
        }

        source = await self.add_source(
            tenant_id,
            SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="llm_json",
                title=title or "External LLM JSON",
                mime_type="application/json",
                content_text=canonical,
                content_hash=content_hash,
                meta=source_meta,
            ),
        )

        summary = await self._process_llm_source(
            tenant_id=tenant_id,
            run_id=run_id,
            source=source,
            parsed_payload=parsed,
            provider=provider,
            model_name=model_name,
            content_hash=content_hash,
            canonical_json=canonical,
            purpose=purpose,
        )

        return summary

    async def process_llm_json_sources_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        allow_fixture: bool = False,
    ) -> dict:
        """Process any pending llm_json sources for a run.

        If allow_fixture is True and no llm_json source exists, a mock fixture
        is loaded from disk (provider=mock) when EXTERNAL_LLM_ENABLED is set.
        """

        sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        llm_sources = [s for s in sources if s.source_type == "llm_json"]

        created_from_fixture = False
        if not llm_sources and allow_fixture:
            provider = os.getenv("EXTERNAL_LLM_PROVIDER", "mock")
            fixture_path = os.getenv(
                "EXTERNAL_LLM_FIXTURE_PATH",
                os.path.join("scripts", "proofs", "fixtures", "llm_json_mock_fixture.json"),
            )
            if provider == "mock" and os.path.exists(fixture_path):
                with open(fixture_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                await self.ingest_llm_json_payload(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    payload=payload,
                    provider=provider,
                    model_name=payload.get("model"),
                    title=payload.get("title") or "Mock LLM JSON",
                    purpose=payload.get("purpose") or "company_discovery",
                )
                created_from_fixture = True
                sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
                llm_sources = [s for s in sources if s.source_type == "llm_json"]

        processed = []
        skipped = []
        for src in llm_sources:
            if (src.meta or {}).get("ingest_stats"):
                skipped.append(str(src.id))
                continue
            try:
                payload_dict = json.loads(src.content_text or "{}")
                parsed = LlmDiscoveryPayload(**payload_dict)
                canonical = self._canonical_json(parsed.canonical_dict())
                content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                summary = await self._process_llm_source(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    source=src,
                    parsed_payload=parsed,
                    provider=(src.meta or {}).get("provider") or payload_dict.get("provider") or "mock",
                    model_name=(src.meta or {}).get("model") or payload_dict.get("model"),
                    content_hash=content_hash,
                    canonical_json=canonical,
                    purpose=(src.meta or {}).get("purpose") or payload_dict.get("purpose") or "company_discovery",
                )
                processed.append(summary)
            except Exception as exc:  # noqa: BLE001
                src.status = "failed"
                src.error_message = str(exc)
                skipped.append(str(src.id))
        await self.db.flush()
        return {
            "processed": processed,
            "skipped": skipped,
            "created_from_fixture": created_from_fixture,
        }

    async def _process_llm_source(
        self,
        tenant_id: str,
        run_id: UUID,
        source: ResearchSourceDocument,
        parsed_payload: LlmDiscoveryPayload,
        provider: str,
        model_name: Optional[str],
        content_hash: str,
        canonical_json: str,
        purpose: str,
    ) -> dict:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        # Prepare existing maps for idempotent inserts
        existing_sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        url_norm_map = {
            self._normalize_url_value(s.url): s
            for s in existing_sources
            if s.url
        }

        discovery_label = provider if provider in {"internal", "manual", "grok", "both"} else "grok"

        prospect_result = await self.db.execute(
            select(CompanyProspect).where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
            )
        )
        prospect_map = {p.name_normalized: p for p in prospect_result.scalars().all()}

        # Upsert enrichment record (idempotent via unique constraint)
        existing_enrichment = None
        enrichment_query = await self.db.execute(
            select(AIEnrichmentRecord).where(
                AIEnrichmentRecord.tenant_id == tenant_id,
                AIEnrichmentRecord.company_research_run_id == run_id,
                AIEnrichmentRecord.purpose == purpose,
                AIEnrichmentRecord.provider == provider,
                AIEnrichmentRecord.content_hash == content_hash,
            )
        )
        existing_enrichment = enrichment_query.scalar_one_or_none()

        if existing_enrichment:
            enrichment = existing_enrichment
        else:
            enrichment = AIEnrichmentRecord(
                tenant_id=tenant_id,
                target_type="COMPANY_RESEARCH_RUN",
                target_id=run_id,
                model_name=model_name,
                enrichment_type="COMPANY_DISCOVERY_JSON",
                payload=parsed_payload.canonical_dict(),
                company_research_run_id=run_id,
                purpose=purpose,
                provider=provider,
                input_scope_hash=content_hash,
                content_hash=content_hash,
                source_document_id=source.id,
                status="success",
            )
            self.db.add(enrichment)

        await self.db.flush()

        stats = {
            "companies_new": 0,
            "companies_existing": 0,
            "evidence_created": 0,
            "urls_created": 0,
            "urls_existing": 0,
        }

        evidence_seen: set[tuple[str, str, str]] = set()

        for company in parsed_payload.companies:
            norm_name = self._normalize_company_name(company.name)
            if not norm_name:
                continue

            existing = prospect_map.get(norm_name)
            if existing:
                stats["companies_existing"] += 1
                existing.discovered_by = self._merge_discovered_by(existing.discovered_by, discovery_label)
                if not getattr(existing, "verification_status", None):
                    existing.verification_status = "unverified"
            else:
                prospect = CompanyProspect(
                    tenant_id=tenant_id,
                    company_research_run_id=run_id,
                    role_mandate_id=run.role_mandate_id,
                    name_raw=company.name,
                    name_normalized=norm_name,
                    website_url=company.website_url,
                    hq_country=self._normalize_country_code(company.hq_country),
                    hq_city=company.hq_city,
                    sector=company.sector or run.sector,
                    subsector=company.subsector,
                    description=company.description,
                    relevance_score=float(company.confidence or 0.0),
                    evidence_score=0.0,
                    status="new",
                    discovered_by=discovery_label,
                    verification_status="unverified",
                    exec_search_enabled=False,
                )
                self.db.add(prospect)
                await self.db.flush()
                prospect_map[norm_name] = prospect
                existing = prospect
                stats["companies_new"] += 1

            # Evidence handling
            for ev in company.evidence or []:
                dedupe_key = (str(existing.id), ev.url, ev.label or ev.kind or "llm_json")
                if dedupe_key in evidence_seen:
                    continue
                evidence_seen.add(dedupe_key)

                evidence = CompanyProspectEvidence(
                    tenant_id=tenant_id,
                    company_prospect_id=existing.id,
                    source_type=ev.kind or "llm_json",
                    source_name=ev.label or (ev.kind or "llm_json"),
                    source_url=str(ev.url),
                    raw_snippet=ev.snippet,
                    source_document_id=source.id,
                    source_content_hash=content_hash,
                )
                self.db.add(evidence)
                stats["evidence_created"] += 1

                # Add URL source for evidence to existing pipeline
                url_norm = self._normalize_url_value(str(ev.url))
                if url_norm and url_norm in url_norm_map:
                    stats["urls_existing"] += 1
                elif url_norm:
                    url_source = await self.add_source(
                        tenant_id,
                        SourceDocumentCreate(
                            company_research_run_id=run_id,
                            source_type="url",
                            title=ev.label or str(ev.url),
                            url=str(ev.url),
                            meta={
                                "kind": "url",
                                "origin": "llm_json",
                                "llm_source_id": str(source.id),
                                "evidence_kind": ev.kind,
                                "evidence_label": ev.label,
                            },
                        ),
                    )
                    url_norm_map[url_norm] = url_source
                    stats["urls_created"] += 1

        source.status = "processed"
        source.error_message = None
        source.meta = {**(source.meta or {}), "ingest_stats": stats, "enrichment_id": str(enrichment.id)}

        await self.db.flush()

        return {
            "source_id": str(source.id),
            "enrichment_id": str(enrichment.id),
            "content_hash": content_hash,
            **stats,
        }

    async def list_executive_eligible_companies(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[CompanyProspect]:
        """List companies approved for executive discovery."""
        result = await self.db.execute(
            select(CompanyProspect).where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
                CompanyProspect.exec_search_enabled.is_(True),
                CompanyProspect.status == "accepted",
            )
        )
        return list(result.scalars().all())

    async def ingest_executive_llm_json_payload(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: dict,
        provider: str,
        model_name: Optional[str],
        title: Optional[str],
    ) -> dict:
        """Ingest executive discovery payload with gating and idempotency."""

        parsed = ExecutiveDiscoveryPayload(**payload)
        canonical = self._canonical_json(parsed.canonical_dict())
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        existing_source = await self.repo.find_source_by_hash(tenant_id, run_id, content_hash)
        if existing_source and existing_source.source_type == "llm_json":
            ingest_meta = {
                "executives_new": 0,
                "executives_existing": 0,
                "evidence_created": 0,
                "urls_created": 0,
                "urls_existing": 0,
                "companies_targeted": 0,
            }
            return {
                "skipped": True,
                "reason": "duplicate_hash",
                "source_id": str(existing_source.id),
                "ingest_stats": ingest_meta,
            }

        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        eligible = await self.list_executive_eligible_companies(tenant_id, run_id)
        eligible_map = {self._normalize_company_name(p.name_normalized or p.name_raw): p for p in eligible}

        requested_companies: list[str] = []
        missing: list[str] = []
        for company in parsed.companies:
            norm = self._normalize_company_name(company.company_normalized or company.company_name)
            if not norm:
                continue
            requested_companies.append(norm)
            prospect = eligible_map.get(norm)
            if not prospect:
                missing.append(norm)

        if not requested_companies:
            raise ValueError("no_companies_in_payload")
        if missing:
            raise ValueError(f"ineligible_companies:{','.join(sorted(set(missing)))}")

        existing_sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        url_norm_map = {self._normalize_url_value(s.url): s for s in existing_sources if s.url}

        source_meta = {
            "kind": "llm_json",
            "provider": provider,
            "model": model_name,
            "purpose": "executive_discovery",
            "schema_version": parsed.schema_version,
        }

        source = await self.add_source(
            tenant_id,
            SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="llm_json",
                title=title or "External Executive LLM JSON",
                mime_type="application/json",
                content_text=canonical,
                content_hash=content_hash,
                meta=source_meta,
            ),
        )

        enrichment_query = await self.db.execute(
            select(AIEnrichmentRecord).where(
                AIEnrichmentRecord.tenant_id == tenant_id,
                AIEnrichmentRecord.company_research_run_id == run_id,
                AIEnrichmentRecord.purpose == "executive_discovery",
                AIEnrichmentRecord.provider == provider,
                AIEnrichmentRecord.content_hash == content_hash,
            )
        )
        enrichment = enrichment_query.scalar_one_or_none()
        if not enrichment:
            enrichment = AIEnrichmentRecord(
                tenant_id=tenant_id,
                target_type="COMPANY_RESEARCH_RUN",
                target_id=run_id,
                model_name=model_name,
                enrichment_type="EXECUTIVE_DISCOVERY_JSON",
                payload=parsed.canonical_dict(),
                company_research_run_id=run_id,
                purpose="executive_discovery",
                provider=provider,
                input_scope_hash=content_hash,
                content_hash=content_hash,
                source_document_id=source.id,
                status="success",
            )
            self.db.add(enrichment)

        await self.db.flush()

        exec_result = await self.db.execute(
            select(ExecutiveProspect).where(
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.company_research_run_id == run_id,
            )
        )
        existing_exec_map: dict[UUID, dict[str, ExecutiveProspect]] = defaultdict(dict)
        for exec_rec in exec_result.scalars().all():
            existing_exec_map[exec_rec.company_prospect_id][exec_rec.name_normalized] = exec_rec

        stats = {
            "executives_new": 0,
            "executives_existing": 0,
            "evidence_created": 0,
            "urls_created": 0,
            "urls_existing": 0,
            "companies_targeted": len(requested_companies),
        }

        evidence_seen: set[tuple[str, str, str]] = set()

        for company in parsed.companies:
            norm = self._normalize_company_name(company.company_normalized or company.company_name)
            if not norm:
                continue
            prospect = eligible_map.get(norm)
            if not prospect:
                continue

            for exec_entry in company.executives or []:
                exec_norm = self._normalize_person_name(exec_entry.name)
                if not exec_norm:
                    continue

                existing_exec = existing_exec_map.get(prospect.id, {}).get(exec_norm)
                if existing_exec:
                    stats["executives_existing"] += 1
                    target_exec = existing_exec
                else:
                    target_exec = ExecutiveProspect(
                        tenant_id=tenant_id,
                        company_research_run_id=run_id,
                        company_prospect_id=prospect.id,
                        name_raw=exec_entry.name,
                        name_normalized=exec_norm,
                        title=exec_entry.title,
                        profile_url=self._normalize_url_value(exec_entry.profile_url),
                        linkedin_url=self._normalize_url_value(exec_entry.linkedin_url),
                        email=exec_entry.email,
                        location=exec_entry.location,
                        confidence=float(exec_entry.confidence or 0.0),
                        status="new",
                        source_label=provider,
                        source_document_id=source.id,
                    )
                    self.db.add(target_exec)
                    await self.db.flush()
                    existing_exec_map[prospect.id][exec_norm] = target_exec
                    stats["executives_new"] += 1

                for ev in exec_entry.evidence or []:
                    dedupe_key = (str(target_exec.id), ev.url or "", ev.label or ev.kind or "executive_llm_json")
                    if dedupe_key in evidence_seen:
                        continue
                    evidence_seen.add(dedupe_key)

                    evidence = ExecutiveProspectEvidence(
                        tenant_id=tenant_id,
                        executive_prospect_id=target_exec.id,
                        source_type=ev.kind or "llm_json",
                        source_name=ev.label or (ev.kind or "llm_json"),
                        source_url=str(ev.url) if ev.url else None,
                        raw_snippet=ev.snippet,
                        evidence_weight=0.5,
                        source_document_id=source.id,
                        source_content_hash=content_hash,
                    )
                    self.db.add(evidence)
                    stats["evidence_created"] += 1

                    url_norm = self._normalize_url_value(str(ev.url)) if ev.url else None
                    if url_norm and url_norm in url_norm_map:
                        stats["urls_existing"] += 1
                    elif url_norm:
                        url_source = await self.add_source(
                            tenant_id,
                            SourceDocumentCreate(
                                company_research_run_id=run_id,
                                source_type="url",
                                title=ev.label or str(ev.url),
                                url=str(ev.url),
                                meta={
                                    "kind": "url",
                                    "origin": "executive_llm_json",
                                    "llm_source_id": str(source.id),
                                    "evidence_kind": ev.kind,
                                    "evidence_label": ev.label,
                                },
                            ),
                        )
                        url_norm_map[url_norm] = url_source
                        stats["urls_created"] += 1

        source.status = "processed"
        source.error_message = None
        source.meta = {**(source.meta or {}), "ingest_stats": stats, "enrichment_id": str(enrichment.id)}

        await self.db.flush()

        return {
            "source_id": str(source.id),
            "enrichment_id": str(enrichment.id),
            "content_hash": content_hash,
            **stats,
        }
    
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

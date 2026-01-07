"""
Company Research Service - business logic layer.

Provides validation and orchestration for company discovery operations.
Phase 1: Backend structures only, no external AI/crawling yet.
"""

import csv
import hashlib
import io
import json
import os
import re
import zipfile
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.repositories.company_research_repo import CompanyResearchRepository
from app.repositories.enrichment_assignment_repository import EnrichmentAssignmentRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.candidate_assignment_repository import CandidateAssignmentRepository
from app.repositories.research_event_repository import ResearchEventRepository
from app.repositories.source_document_repository import SourceDocumentRepository
from app.models.research_event import ResearchEvent
from app.models.source_document import SourceDocument
from app.models.pipeline_stage import PipelineStage
from app.models.candidate_assignment import CandidateAssignment
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
    ExecutiveMergeDecision,
)
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.models.activity_log import ActivityLog
from app.services.ai_proposal_service import AIProposalService
from app.services.entity_resolution_service import EntityResolutionService
from app.services.canonical_people_service import CanonicalPeopleService
from app.services.canonical_company_service import CanonicalCompanyService
from app.services.discovery_provider import get_discovery_provider
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
    ProspectSignalEvidence,
    RunPack,
    PackCompany,
    PackExecutive,
    PackMergeDecision,
    PackAuditEvent,
    PackAuditSummary,
    ResearchEventCreate,
)
from app.schemas.source_document import SourceDocumentCreate as ResearchEventSourceDocumentCreate
from app.schemas.candidate import CandidateCreate
from app.schemas.contact import ContactCreate
from app.schemas.candidate_assignment import CandidateAssignmentCreate
from app.utils.url_canonicalizer import canonicalize_url


class CompanyResearchService:
    """Service layer for company research operations."""

    REVIEW_STATUSES = {"new", "accepted", "hold", "rejected"}
    EXEC_VERIFICATION_STATUSES = {"unverified", "partial", "verified"}
    EXEC_VERIFICATION_ORDER = {
        "unverified": 0,
        "partial": 1,
        "verified": 2,
    }
    EXEC_PROVENANCE_ORDER = {
        "external": 0,
        "internal": 1,
        "both": 2,
    }

    EXPORT_MAX_ZIP_BYTES = settings.EXPORT_PACK_MAX_ZIP_BYTES
    EXPORT_DEFAULT_MAX_COMPANIES = settings.EXPORT_PACK_DEFAULT_MAX_COMPANIES
    EXPORT_DEFAULT_MAX_EXECUTIVES = settings.EXPORT_PACK_DEFAULT_MAX_EXECUTIVES
    EXPORT_MAX_COMPANIES = settings.EXPORT_PACK_MAX_COMPANIES
    EXPORT_MAX_EXECUTIVES = settings.EXPORT_PACK_MAX_EXECUTIVES
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)
        self.assignment_repo = EnrichmentAssignmentRepository(db)

    def _split_name(self, full_name: str) -> tuple[str, str]:
        tokens = [token for token in (full_name or "").strip().split() if token]
        if not tokens:
            return "Executive", "Prospect"
        if len(tokens) == 1:
            return tokens[0], tokens[0]
        return tokens[0], " ".join(tokens[1:])
    
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
                "step_key": "classify_sources",
                "step_order": 17,
                "rationale": "Classify extracted sources for duplicates and junk before processing",
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
                "step_key": "entity_resolution",
                "step_order": 25,
                "rationale": "Resolve run-scoped executive duplicates with evidence-first merges",
                "enabled": True,
                "max_attempts": 2,
            },
            {
                "step_key": "canonical_people_resolution",
                "step_order": 27,
                "rationale": "Build tenant-wide canonical people (email-first, evidence-first)",
                "enabled": True,
                "max_attempts": 2,
            },
            {
                "step_key": "canonical_company_resolution",
                "step_order": 28,
                "rationale": "Build tenant-wide canonical companies (domain-first, evidence-first)",
                "enabled": True,
                "max_attempts": 2,
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
        review_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        discovered_by: Optional[str] = None,
        exec_search_enabled: Optional[bool] = None,
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
            review_status=review_status,
            verification_status=verification_status,
            discovered_by=discovered_by,
            exec_search_enabled=exec_search_enabled,
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
        review_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        discovered_by: Optional[str] = None,
        exec_search_enabled: Optional[bool] = None,
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
            review_status=review_status,
            verification_status=verification_status,
            discovered_by=discovered_by,
            exec_search_enabled=exec_search_enabled,
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

    async def update_prospect_review_status(
        self,
        tenant_id: str,
        prospect_id: UUID,
        review_status: str,
        actor: Optional[str] = None,
    ) -> Optional[CompanyProspect]:
        """Update review_status with deterministic audit logging."""

        if review_status not in self.REVIEW_STATUSES:
            raise ValueError("invalid_review_status")

        prospect = await self.repo.get_company_prospect(tenant_id, prospect_id)
        if not prospect:
            return None

        old_status = getattr(prospect, "review_status", "new")
        if old_status == review_status:
            return prospect

        prospect.review_status = review_status

        self.db.add(
            ActivityLog(
                tenant_id=tenant_id,
                role_id=prospect.role_mandate_id,
                type="PROSPECT_REVIEW_STATUS",
                message=f"prospect_id={prospect_id} run_id={prospect.company_research_run_id} review_status {old_status}->{review_status}",
                created_by=actor or "system",
            )
        )

        await self.db.flush()
        await self.db.refresh(prospect)
        return prospect

    async def update_executive_verification_status(
        self,
        tenant_id: str,
        executive_id: UUID,
        verification_status: str,
        actor: Optional[str] = None,
    ) -> Optional[ExecutiveProspect]:
        """Update executive verification status with audit logging and no downgrades."""

        if verification_status not in self.EXEC_VERIFICATION_STATUSES:
            raise ValueError("invalid_verification_status")

        executive = await self.repo.get_executive_prospect(tenant_id, executive_id)
        if not executive:
            return None

        current_status = getattr(executive, "verification_status", "unverified")
        if self.EXEC_VERIFICATION_ORDER.get(verification_status, 0) < self.EXEC_VERIFICATION_ORDER.get(current_status, 0):
            raise ValueError("downgrade_not_allowed")

        if current_status == verification_status:
            return executive

        executive.verification_status = verification_status

        evidence_source_ids: list[str] = []
        for ev in getattr(executive, "evidence", []) or []:
            if ev.source_document_id:
                evidence_source_ids.append(str(ev.source_document_id))
        evidence_source_ids = list(dict.fromkeys(evidence_source_ids))

        role_id = None
        if getattr(executive, "company_prospect", None):
            role_id = getattr(executive.company_prospect, "role_mandate_id", None)

        self.db.add(
            ActivityLog(
                tenant_id=tenant_id,
                role_id=role_id,
                type="EXEC_VERIFICATION_STATUS",
                message=(
                    f"executive_id={executive_id} run_id={executive.company_research_run_id} "
                    f"verification_status {current_status}->{verification_status} "
                    f"evidence_source_documents={','.join(evidence_source_ids) or 'none'} "
                    f"evidence_count={len(getattr(executive, 'evidence', []) or [])}"
                ),
                created_by=actor or "system",
            )
        )

        await self.db.flush()
        await self.db.refresh(executive)
        return executive

    async def update_executive_review_status(
        self,
        tenant_id: str,
        executive_id: UUID,
        review_status: str,
        actor: Optional[str] = None,
    ) -> Optional[ExecutiveProspect]:
        """Update executive review_status with deterministic audit logging."""

        if review_status not in self.REVIEW_STATUSES:
            raise ValueError("invalid_review_status")

        executive = await self.repo.get_executive_prospect(tenant_id, executive_id)
        if not executive:
            return None

        current_status = getattr(executive, "review_status", "new")
        if current_status == review_status:
            return executive

        executive.review_status = review_status

        role_id = None
        if getattr(executive, "company_prospect", None):
            role_id = getattr(executive.company_prospect, "role_mandate_id", None)

        self.db.add(
            ActivityLog(
                tenant_id=tenant_id,
                role_id=role_id,
                type="EXECUTIVE_REVIEW_STATUS",
                message=(
                    f"executive_id={executive_id} prospect_id={executive.company_prospect_id} "
                    f"run_id={executive.company_research_run_id} review_status {current_status}->{review_status}"
                ),
                created_by=actor or "system",
            )
        )

        await self.db.flush()
        await self.db.refresh(executive)
        return executive

    async def _resolve_pipeline_stage(
        self,
        tenant_uuid: UUID,
        requested_stage_id: Optional[UUID],
    ) -> tuple[Optional[UUID], Optional[str]]:
        """Return (stage_id, stage_name) for the requested or default initial stage."""

        query = select(PipelineStage).where(PipelineStage.tenant_id == tenant_uuid)
        if requested_stage_id:
            query = query.where(PipelineStage.id == requested_stage_id)

        query = query.order_by(PipelineStage.order_index.asc(), PipelineStage.created_at.asc())
        result = await self.db.execute(query)
        stage = result.scalars().first()

        if requested_stage_id and not stage:
            raise ValueError("stage_not_found")

        if stage:
            return stage.id, stage.name

        return None, None

    async def create_executive_pipeline(
        self,
        tenant_id: str,
        executive_id: UUID,
        *,
        assignment_status: Optional[str] = None,
        current_stage_id: Optional[UUID] = None,
        role_id: Optional[UUID] = None,
        notes: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> Optional[dict]:
        """Create ATS candidate/contact/assignment from an accepted executive prospect with audit/evidence."""

        executive = await self.repo.get_executive_prospect(tenant_id, executive_id)
        if not executive:
            return None

        if getattr(executive, "review_status", "new") != "accepted":
            raise ValueError("review_status_not_accepted")

        prospect = getattr(executive, "company_prospect", None)
        if not prospect:
            raise ValueError("prospect_missing")

        resolved_role_id = role_id or getattr(prospect, "role_mandate_id", None)
        company_id = getattr(prospect, "normalized_company_id", None)
        company_name = getattr(prospect, "name_normalized", None) or getattr(prospect, "name_raw", None)

        if role_id and resolved_role_id and resolved_role_id != role_id:
            raise ValueError("role_mismatch")

        if not resolved_role_id:
            raise ValueError("role_missing")

        first_name, last_name = self._split_name(
            getattr(executive, "name_normalized", None)
            or getattr(executive, "name_raw", None)
            or "Executive Prospect",
        )

        tenant_uuid = UUID(str(tenant_id))
        stage_id, stage_name = await self._resolve_pipeline_stage(tenant_uuid, current_stage_id)

        candidate_repo = CandidateRepository(self.db)
        contact_repo = ContactRepository(self.db)
        assignment_repo = CandidateAssignmentRepository(self.db)

        evidence_ids: list[UUID] = []
        if executive.source_document_id:
            evidence_ids.append(executive.source_document_id)
        for ev in getattr(executive, "evidence", []) or []:
            if ev.source_document_id:
                evidence_ids.append(ev.source_document_id)
        evidence_ids = list(dict.fromkeys(evidence_ids))

        # Idempotency path: reuse existing pipeline artifacts tied to this executive.
        payload_exec_id = ResearchEvent.raw_payload["executive_id"].astext
        existing_event_row = await self.db.execute(
            select(ResearchEvent, SourceDocument.id)
            .outerjoin(SourceDocument, SourceDocument.research_event_id == ResearchEvent.id)
            .where(
                ResearchEvent.tenant_id == tenant_uuid,
                ResearchEvent.source_type == "executive_review",
                ResearchEvent.entity_type == "CANDIDATE",
                payload_exec_id == str(executive_id),
            )
            .order_by(ResearchEvent.created_at.asc(), SourceDocument.created_at.asc())
        )

        existing = existing_event_row.first()
        if existing:
            research_event, source_document_id = existing
            payload = research_event.raw_payload or {}

            candidate_id = research_event.entity_id
            contact_id_text = payload.get("contact_id")
            assignment_id_text = payload.get("assignment_id")
            assignment_status_val = payload.get("assignment_status") or assignment_status or "sourced"
            payload_stage_id = payload.get("pipeline_stage_id") or payload.get("current_stage_id")
            payload_stage_name = payload.get("pipeline_stage_name") or stage_name
            payload_role_id = payload.get("role_mandate_id")
            payload_evidence_ids = [UUID(str(e)) for e in payload.get("evidence_source_document_ids") or [] if e]

            assignment_uuid = None
            try:
                assignment_uuid = UUID(str(assignment_id_text)) if assignment_id_text else None
            except (ValueError, TypeError):
                assignment_uuid = None

            contact_uuid = None
            try:
                contact_uuid = UUID(str(contact_id_text)) if contact_id_text else None
            except (ValueError, TypeError):
                contact_uuid = None

            assignment = None
            if assignment_uuid:
                assignment = await assignment_repo.get_by_id(tenant_id, assignment_uuid)
                if assignment and assignment.status:
                    assignment_status_val = assignment.status

            pipeline_stage_uuid = None
            if assignment and assignment.current_stage_id:
                pipeline_stage_uuid = assignment.current_stage_id
            elif payload_stage_id:
                try:
                    pipeline_stage_uuid = UUID(str(payload_stage_id))
                except (ValueError, TypeError):
                    pipeline_stage_uuid = None

            stage_lookup_id, stage_lookup_name = (None, None)
            if pipeline_stage_uuid:
                stage_lookup_id, stage_lookup_name = await self._resolve_pipeline_stage(tenant_uuid, pipeline_stage_uuid)

            # Persist back-links for idempotency if missing
            if candidate_id and not getattr(executive, "candidate_id", None):
                executive.candidate_id = candidate_id
            if contact_uuid and not getattr(executive, "contact_id", None):
                executive.contact_id = contact_uuid
            if assignment and not getattr(executive, "candidate_assignment_id", None):
                executive.candidate_assignment_id = assignment.id
            await self.db.flush()

            return {
                "candidate_id": candidate_id,
                "contact_id": contact_uuid,
                "assignment_id": assignment.id if assignment else assignment_uuid,
                "role_id": resolved_role_id or payload_role_id,
                "pipeline_stage_id": stage_lookup_id,
                "pipeline_stage_name": stage_lookup_name or payload_stage_name,
                "assignment_status": assignment_status_val,
                "evidence_source_document_ids": payload_evidence_ids or evidence_ids,
                "research_event_id": research_event.id,
                "source_document_id": source_document_id,
                "review_status": getattr(executive, "review_status", "new"),
                "idempotent": True,
            }

        # Creation path
        candidate = None
        if getattr(executive, "candidate_id", None):
            candidate = await candidate_repo.get_by_id(tenant_id, executive.candidate_id)

        if not candidate:
            candidate = await candidate_repo.create(
                tenant_id,
                CandidateCreate(
                    tenant_id=tenant_id,
                    first_name=first_name,
                    last_name=last_name,
                    email=executive.email,
                    current_title=executive.title,
                    current_company=company_name,
                    location=executive.location,
                    linkedin_url=executive.linkedin_url,
                ),
            )

        contact = None
        if getattr(executive, "contact_id", None):
            contact = await contact_repo.get_by_id(tenant_id, executive.contact_id)
        elif company_id:
            contact = await contact_repo.create(
                tenant_id,
                ContactCreate(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    first_name=first_name,
                    last_name=last_name,
                    email=executive.email,
                    role_title=executive.title,
                    notes=(
                        f"Created from executive prospect {executive_id} "
                        f"for run {executive.company_research_run_id}"
                    ),
                ),
            )

        assignment = None
        if getattr(executive, "candidate_assignment_id", None):
            assignment = await assignment_repo.get_by_id(tenant_id, executive.candidate_assignment_id)

        if not assignment:
            assignment = await assignment_repo.get_by_candidate_and_role(
                tenant_id=tenant_id,
                candidate_id=candidate.id,
                role_id=resolved_role_id,
            )

        if not assignment:
            assignment = await assignment_repo.create(
                tenant_id,
                CandidateAssignmentCreate(
                    tenant_id=tenant_id,
                    candidate_id=candidate.id,
                    role_id=resolved_role_id,
                    status=assignment_status or "sourced",
                    current_stage_id=stage_id,
                    source="executive_review",
                    notes=notes,
                ),
            )
        elif stage_id and assignment.current_stage_id is None:
            assignment.current_stage_id = stage_id
            await self.db.flush()

        pipeline_stage_uuid = assignment.current_stage_id or stage_id
        stage_lookup_id, stage_lookup_name = (None, None)
        if pipeline_stage_uuid:
            stage_lookup_id, stage_lookup_name = await self._resolve_pipeline_stage(tenant_uuid, pipeline_stage_uuid)

        assignment_status_value = assignment.status or assignment_status or "sourced"

        research_event_repo = ResearchEventRepository(self.db)
        research_event = await research_event_repo.create(
            tenant_uuid,
            ResearchEventCreate(
                tenant_id=tenant_uuid,
                source_type="executive_review",
                source_url=executive.profile_url or executive.linkedin_url,
                entity_type="CANDIDATE",
                entity_id=candidate.id,
                raw_payload={
                    "executive_id": str(executive_id),
                    "company_prospect_id": str(executive.company_prospect_id),
                    "company_research_run_id": str(executive.company_research_run_id),
                    "role_mandate_id": str(resolved_role_id) if resolved_role_id else None,
                    "assignment_id": str(assignment.id),
                    "assignment_status": assignment_status_value,
                    "contact_id": str(getattr(contact, "id", None)) if contact else None,
                    "pipeline_stage_id": str(stage_lookup_id) if stage_lookup_id else None,
                    "pipeline_stage_name": stage_lookup_name,
                    "review_status": getattr(executive, "review_status", "new"),
                    "verification_status": getattr(executive, "verification_status", None),
                    "provenance": getattr(executive, "discovered_by", None),
                    "evidence_source_document_ids": [str(eid) for eid in evidence_ids],
                    "source_document_id": str(executive.source_document_id) if executive.source_document_id else None,
                },
            ),
        )

        source_doc_repo = SourceDocumentRepository(self.db)
        source_document = await source_doc_repo.create(
            tenant_uuid,
            ResearchEventSourceDocumentCreate(
                tenant_id=tenant_uuid,
                research_event_id=research_event.id,
                document_type="executive_review_pipeline",
                title=(
                    f"Executive {executive.name_normalized or executive.name_raw} pipeline promotion"
                ),
                url=executive.profile_url or executive.linkedin_url,
                text_content=json.dumps(
                    {
                        "executive_id": str(executive_id),
                        "candidate_id": str(candidate.id),
                        "assignment_id": str(assignment.id),
                        "evidence_source_document_ids": [str(eid) for eid in evidence_ids],
                        "pipeline_stage_id": str(stage_lookup_id) if stage_lookup_id else None,
                        "pipeline_stage_name": stage_lookup_name,
                    },
                    sort_keys=True,
                ),
                doc_metadata={
                    "company_name": company_name,
                    "role_mandate_id": str(resolved_role_id) if resolved_role_id else None,
                    "review_status": getattr(executive, "review_status", "new"),
                    "verification_status": getattr(executive, "verification_status", None),
                    "provenance": getattr(executive, "discovered_by", None),
                    "executive_source_document_id": str(executive.source_document_id) if executive.source_document_id else None,
                    "executive_evidence_source_document_ids": [str(eid) for eid in evidence_ids],
                    "pipeline_stage_id": str(stage_lookup_id) if stage_lookup_id else None,
                    "pipeline_stage_name": stage_lookup_name,
                },
            ),
        )

        executive.candidate_id = candidate.id
        executive.contact_id = getattr(contact, "id", None)
        executive.candidate_assignment_id = assignment.id

        evidence_text = "|".join(str(eid) for eid in evidence_ids)

        self.db.add(
            ActivityLog(
                tenant_id=tenant_id,
                role_id=resolved_role_id,
                candidate_id=candidate.id,
                contact_id=getattr(contact, "id", None),
                type="EXECUTIVE_PIPELINE_CREATE",
                message=(
                    f"executive_id={executive_id} candidate_id={candidate.id} "
                    f"assignment_id={assignment.id} role_id={resolved_role_id} stage_id={stage_lookup_id} "
                    f"stage_name={stage_lookup_name or ''} evidence_ids={evidence_text}"
                ),
                created_by=actor or "system",
            )
        )

        if stage_lookup_id:
            self.db.add(
                ActivityLog(
                    tenant_id=tenant_id,
                    role_id=resolved_role_id,
                    candidate_id=candidate.id,
                    contact_id=getattr(contact, "id", None),
                    type="EXECUTIVE_PIPELINE_STAGE_SET",
                    message=(
                        f"candidate_id={candidate.id} assignment_id={assignment.id} "
                        f"stage_id={stage_lookup_id} stage_name={stage_lookup_name or ''}"
                    ),
                    created_by=actor or "system",
                )
            )

        await self.db.flush()

        return {
            "candidate_id": candidate.id,
            "contact_id": getattr(contact, "id", None),
            "assignment_id": assignment.id,
            "role_id": resolved_role_id,
            "pipeline_stage_id": stage_lookup_id,
            "pipeline_stage_name": stage_lookup_name,
            "assignment_status": assignment_status_value,
            "evidence_source_document_ids": evidence_ids,
            "research_event_id": research_event.id,
            "source_document_id": source_document.id,
            "review_status": getattr(executive, "review_status", "new"),
            "idempotent": False,
        }
    
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
    # Explainable Prospect Ranking (Stage 7.3)
    # ====================================================================

    async def rank_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        status: Optional[str] = None,
        min_relevance_score: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """Deterministically rank prospects with evidence-backed signals."""

        prospects = await self.repo.list_all_company_prospects_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            status=status,
            min_relevance_score=min_relevance_score,
        )

        prospect_ids = [p.id for p in prospects]
        link_records = await self.repo.list_canonical_links_for_prospects(
            tenant_id=tenant_id,
            prospect_ids=prospect_ids,
            run_id=run_id,
        )

        links_by_prospect: Dict[UUID, List] = defaultdict(list)
        for link in link_records:
            links_by_prospect[link.company_entity_id].append(link)

        canonical_ids = []
        for prospect in prospects:
            if prospect.normalized_company_id:
                canonical_ids.append(prospect.normalized_company_id)
            for link in links_by_prospect.get(prospect.id, []):
                canonical_ids.append(link.canonical_company_id)

        assignment_records = await self.assignment_repo.list_for_company_ids(
            tenant_id=tenant_id,
            canonical_ids=list({cid for cid in canonical_ids if cid}),
        )

        assignments_by_company: Dict[UUID, List] = defaultdict(list)
        for assignment in assignment_records:
            assignments_by_company[assignment.target_canonical_id].append(assignment)

        ranked: List[dict] = []
        for prospect in prospects:
            primary_link = links_by_prospect.get(prospect.id, [None])[0]
            canonical_id = prospect.normalized_company_id or (primary_link.canonical_company_id if primary_link else None)

            components: Dict[str, float] = {}
            score = float(prospect.relevance_score or 0.0)
            components["ai_relevance"] = score

            evidence_component = float(prospect.evidence_score or 0.0) * 0.2
            if evidence_component:
                components["evidence_score"] = evidence_component
                score += evidence_component

            why_included: List[ProspectSignalEvidence] = []

            if canonical_id:
                for assignment in assignments_by_company.get(canonical_id, []):
                    bonus = 0.0
                    field_key = assignment.field_key
                    value = assignment.value_json
                    confidence = float(assignment.confidence or 0.0)

                    if field_key == "hq_country" and prospect.hq_country:
                        normalized_value = assignment.value_normalized or str(value)
                        if normalized_value and str(prospect.hq_country).lower() == str(normalized_value).lower():
                            bonus = confidence * 0.2
                            components["hq_country_match"] = components.get("hq_country_match", 0.0) + bonus

                    elif field_key == "ownership_signal":
                        bonus = confidence * 0.1
                        components["ownership_signal"] = components.get("ownership_signal", 0.0) + bonus

                    elif field_key == "industry_keywords":
                        keywords: List[str] = []
                        if isinstance(value, list):
                            keywords = [str(v).lower() for v in value]
                        elif isinstance(value, str):
                            keywords = [value.lower()]

                        sector_text = f"{prospect.sector or ''} {prospect.subsector or ''}".lower()
                        matched = any(kw and kw in sector_text for kw in keywords)

                        bonus = confidence * (0.15 if matched else 0.05)
                        key = "industry_keywords_match" if matched else "industry_keywords_presence"
                        components[key] = components.get(key, 0.0) + bonus

                    if bonus:
                        score += bonus
                        why_included.append(
                            ProspectSignalEvidence(
                                field_key=field_key,
                                value=value,
                                value_normalized=assignment.value_normalized,
                                confidence=confidence,
                                source_document_id=assignment.source_document_id,
                            )
                        )

            ranked.append(
                {
                    "id": prospect.id,
                    "name_normalized": prospect.name_normalized,
                    "normalized_company_id": canonical_id,
                    "website_url": prospect.website_url,
                    "hq_country": prospect.hq_country,
                    "sector": prospect.sector,
                    "subsector": prospect.subsector,
                    "relevance_score": float(prospect.relevance_score or 0.0),
                    "evidence_score": float(prospect.evidence_score or 0.0),
                    "is_pinned": prospect.is_pinned,
                    "manual_priority": prospect.manual_priority,
                    "review_status": getattr(prospect, "review_status", "new"),
                    "discovered_by": getattr(prospect, "discovered_by", "internal"),
                    "verification_status": getattr(prospect, "verification_status", "unverified"),
                    "exec_search_enabled": getattr(prospect, "exec_search_enabled", False),
                    "computed_score": score,
                    "score_components": components,
                    "why_included": why_included,
                    "_tie_breaker_name": prospect.name_normalized.lower(),
                }
            )

        ranked_sorted = sorted(
            ranked,
            key=lambda item: (
                not item["is_pinned"],
                item["manual_priority"] is None,
                item["manual_priority"] if item["manual_priority"] is not None else 0,
                -item["computed_score"],
                -item["evidence_score"],
                item["_tie_breaker_name"],
            ),
        )

        sliced = ranked_sorted[offset : offset + limit]
        for item in sliced:
            item.pop("_tie_breaker_name", None)
        return sliced

    # ====================================================================
    # Executive Ranking (Phase 7.11)
    # ====================================================================

    async def rank_executives_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        company_prospect_id: Optional[UUID] = None,
        provenance: Optional[str] = None,
        verification_status: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """Deterministically rank executives with explainability and stable tie-breakers."""

        rows = await self.repo.list_executive_rank_inputs(
            tenant_id=tenant_id,
            run_id=run_id,
            company_prospect_id=company_prospect_id,
        )

        ver_weights = {
            "verified": 1000.0,
            "partial": 500.0,
            "unverified": 0.0,
        }
        prov_weights = {
            "both": 200.0,
            "internal": 100.0,
            "external": 100.0,
        }

        provenance_filter = provenance.lower() if provenance else None
        verification_filter = verification_status.lower() if verification_status else None
        query_filter = q.lower() if q else None

        ranked: List[dict] = []
        for row in rows:
            exec_row = row.get("executive")
            company_row = row.get("company")
            evidence_ids_raw = row.get("evidence_source_document_ids") or []

            evidence_ids_sorted = sorted(
                {UUID(str(eid)) for eid in evidence_ids_raw if eid},
                key=lambda eid: str(eid),
            )

            provenance_value = (
                (getattr(exec_row, "discovered_by", None) or getattr(exec_row, "source_label", None) or "")
                .strip()
                .lower()
            )
            provenance_value = provenance_value or None

            verification_value = (
                (getattr(exec_row, "verification_status", None) or getattr(company_row, "verification_status", None) or "unverified")
                .strip()
                .lower()
            )

            if provenance_filter and (provenance_value or "") != provenance_filter:
                continue
            if verification_filter and verification_value != verification_filter:
                continue
            if company_prospect_id and getattr(exec_row, "company_prospect_id", None) != company_prospect_id:
                continue

            display_name = (
                getattr(exec_row, "name_normalized", None)
                or getattr(exec_row, "name_raw", None)
                or getattr(exec_row, "name", None)
                or ""
            )
            title = getattr(exec_row, "title", None) or ""

            if query_filter:
                if query_filter not in display_name.lower() and query_filter not in title.lower():
                    continue

            ver_weight = float(ver_weights.get(verification_value, 0.0))
            prov_weight = float(prov_weights.get(provenance_value, 0.0)) if provenance_value else 0.0
            evidence_weight = float(min(len(evidence_ids_sorted) * 10.0, 100.0))

            rank_score = float(ver_weight + prov_weight + evidence_weight)

            reasons = [
                {
                    "code": "VERIFICATION_STATUS",
                    "label": f"verification_status={verification_value or 'unknown'}",
                    "weight": ver_weight,
                    "evidence_source_document_ids": [],
                },
                {
                    "code": "PROVENANCE",
                    "label": f"provenance={provenance_value or 'unknown'}",
                    "weight": prov_weight,
                    "evidence_source_document_ids": [],
                },
                {
                    "code": "EVIDENCE_COVERAGE",
                    "label": "evidence_coverage",
                    "weight": evidence_weight,
                    "evidence_source_document_ids": evidence_ids_sorted,
                },
            ]

            ranked.append(
                {
                    "executive_id": exec_row.id,
                    "company_prospect_id": exec_row.company_prospect_id,
                    "display_name": display_name,
                    "title": title or None,
                    "provenance": provenance_value,
                    "verification_status": verification_value,
                    "rank_score": rank_score,
                    "rank_position": 0,
                    "evidence_source_document_ids": evidence_ids_sorted,
                    "why_ranked": reasons,
                }
            )

        ranked_sorted = sorted(
            ranked,
            key=lambda item: (
                -item["rank_score"],
                -self.EXEC_VERIFICATION_ORDER.get(item.get("verification_status") or "", -1),
                -self.EXEC_PROVENANCE_ORDER.get(item.get("provenance") or "", -1),
                str(item["executive_id"]),
            ),
        )

        for idx, item in enumerate(ranked_sorted, start=1):
            item["rank_position"] = idx

        return ranked_sorted[offset : offset + limit]

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

    async def list_executive_prospects_with_evidence(
        self,
        tenant_id: str,
        run_id: UUID,
        canonical_company_id: Optional[UUID] = None,
        company_prospect_id: Optional[UUID] = None,
        discovered_by: Optional[str] = None,
        verification_status: Optional[str] = None,
    ) -> List[dict]:
        """List executives for a run with evidence pointers and stable ordering."""

        base_query = (
            select(ExecutiveProspect, CompanyProspect)
            .join(CompanyProspect, CompanyProspect.id == ExecutiveProspect.company_prospect_id)
            .where(
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.company_research_run_id == run_id,
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
            )
        )

        if company_prospect_id:
            base_query = base_query.where(ExecutiveProspect.company_prospect_id == company_prospect_id)
        if discovered_by:
            base_query = base_query.where(ExecutiveProspect.discovered_by == discovered_by)
        if verification_status:
            base_query = base_query.where(ExecutiveProspect.verification_status == verification_status)

        result = await self.db.execute(base_query)
        exec_and_companies = result.all()
        if not exec_and_companies:
            return []

        prospect_ids = [company.id for _, company in exec_and_companies]
        canonical_links = await self.repo.list_canonical_links_for_prospects(
            tenant_id=tenant_id,
            prospect_ids=prospect_ids,
            run_id=run_id,
        )
        canonical_by_prospect: Dict[UUID, UUID] = {}
        for link in canonical_links:
            canonical_by_prospect.setdefault(link.company_entity_id, link.canonical_company_id)

        exec_ids = [exec_row.id for exec_row, _ in exec_and_companies]
        evidence_rows = await self.repo.list_executive_evidence_for_exec_ids(tenant_id, exec_ids)
        evidence_map: Dict[UUID, List[ExecutiveProspectEvidence]] = defaultdict(list)
        for ev in evidence_rows:
            evidence_map[ev.executive_prospect_id].append(ev)

        filtered_triplets: List[tuple[ExecutiveProspect, CompanyProspect, Optional[UUID]]] = []
        for exec_row, company in exec_and_companies:
            canonical_id = company.normalized_company_id or canonical_by_prospect.get(company.id)
            if canonical_company_id and canonical_id != canonical_company_id:
                continue
            filtered_triplets.append((exec_row, company, canonical_id))

        sorted_triplets = sorted(
            filtered_triplets,
            key=lambda row: (
                (row[1].name_normalized or row[1].name_raw or "").lower(),
                row[0].name_normalized.lower(),
                row[0].title or "",
            ),
        )

        payload: List[dict] = []
        for exec_row, company, canonical_id in sorted_triplets:
            evidence_items = evidence_map.get(exec_row.id, [])
            evidence_payload = [
                {
                    "id": ev.id,
                    "executive_prospect_id": ev.executive_prospect_id,
                    "source_type": ev.source_type,
                    "source_name": ev.source_name,
                    "source_url": ev.source_url,
                    "raw_snippet": ev.raw_snippet,
                    "evidence_weight": float(ev.evidence_weight or 0.0),
                    "source_document_id": ev.source_document_id,
                    "source_content_hash": ev.source_content_hash,
                }
                for ev in evidence_items
            ]

            evidence_source_document_ids = [
                ev.source_document_id for ev in evidence_items if ev.source_document_id
            ]

            payload.append(
                {
                    "id": exec_row.id,
                    "run_id": exec_row.company_research_run_id,
                    "company_prospect_id": exec_row.company_prospect_id,
                    "company_name": company.name_normalized or company.name_raw,
                    "canonical_company_id": canonical_id,
                    "discovered_by": exec_row.discovered_by,
                    "provenance": exec_row.discovered_by,
                    "verification_status": getattr(exec_row, "verification_status", None) or getattr(company, "verification_status", None),
                    "review_status": getattr(exec_row, "review_status", "new"),
                    "name": exec_row.name_raw,
                    "name_normalized": exec_row.name_normalized,
                    "title": exec_row.title,
                    "profile_url": exec_row.profile_url,
                    "linkedin_url": exec_row.linkedin_url,
                    "email": exec_row.email,
                    "location": exec_row.location,
                    "confidence": float(exec_row.confidence or 0.0),
                    "status": exec_row.status,
                    "source_label": exec_row.source_label,
                    "source_document_id": exec_row.source_document_id,
                    "evidence_source_document_ids": list(dict.fromkeys(evidence_source_document_ids)),
                    "evidence": evidence_payload,
                }
            )

        return payload

    async def compare_executives(
        self,
        tenant_id: str,
        run_id: UUID,
        canonical_company_id: Optional[UUID] = None,
    ) -> dict:
        exec_rows = await self.list_executive_prospects_with_evidence(
            tenant_id=tenant_id,
            run_id=run_id,
            canonical_company_id=canonical_company_id,
        )

        exec_map: dict[UUID, dict] = {row["id"]: row for row in exec_rows}
        if not exec_rows:
            return {
                "matched_or_both": [],
                "internal_only": [],
                "external_only": [],
                "candidate_matches": [],
            }

        response_source_ids: set[UUID] = set()
        evidence_source_ids: set[UUID] = set()
        for row in exec_rows:
            if row.get("source_document_id"):
                response_source_ids.add(row["source_document_id"])
            for ev_id in row.get("evidence_source_document_ids") or []:
                evidence_source_ids.add(ev_id)

        all_source_ids = list(response_source_ids | evidence_source_ids)
        sources = await self.repo.list_source_documents_by_ids(tenant_id, all_source_ids)
        source_map = {src.id: src for src in sources}

        enrichments = await self.repo.list_enrichment_records_for_sources(tenant_id, list(response_source_ids))
        enrichment_map: dict[UUID, UUID] = {row.source_document_id: row.id for row in enrichments}

        decisions = await self.repo.list_merge_decisions_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            canonical_company_id=canonical_company_id,
        )
        decision_map: dict[tuple[UUID, UUID], ExecutiveMergeDecision] = {}
        for dec in decisions:
            key = (dec.left_executive_id, dec.right_executive_id)
            decision_map[key] = dec
            decision_map[(dec.right_executive_id, dec.left_executive_id)] = dec

        def _engine_block(exec_row: dict) -> dict:
            resp_id = exec_row.get("source_document_id")
            request_id = None
            if resp_id and resp_id in source_map:
                meta = source_map[resp_id].meta or {}
                request_id = meta.get("request_source_id")
            evidence_ids = [UUID(str(eid)) for eid in (exec_row.get("evidence_source_document_ids") or [])]
            return {
                "request_source_document_id": request_id,
                "response_source_document_id": resp_id,
                "evidence_source_document_ids": evidence_ids,
                "enrichment_record_id": enrichment_map.get(resp_id),
            }

        def _leaf(exec_row: dict, engine_label: str) -> dict:
            return {
                "id": exec_row["id"],
                "company_prospect_id": exec_row["company_prospect_id"],
                "canonical_company_id": exec_row.get("canonical_company_id"),
                "name": exec_row.get("name"),
                "title": exec_row.get("title"),
                "provenance": exec_row.get("provenance") or exec_row.get("discovered_by"),
                "discovered_by": exec_row.get("discovered_by"),
                "source_label": exec_row.get("source_label"),
                "verification_status": exec_row.get("verification_status"),
                "engine": engine_label,
                "evidence": _engine_block(exec_row),
            }

        def _company_key(row: dict) -> str:
            if row.get("canonical_company_id"):
                return f"canon:{row['canonical_company_id']}"
            return f"prospect:{row.get('company_prospect_id')}"

        matched_or_both: list[dict] = []
        internal_only: list[dict] = []
        external_only: list[dict] = []
        candidate_matches: list[dict] = []

        used: set[UUID] = set()

        both_rows = [row for row in exec_rows if (row.get("discovered_by") or row.get("provenance")) == "both"]
        for row in both_rows:
            used.add(row["id"])
            matched_or_both.append(
                {
                    "company_prospect_id": row.get("company_prospect_id"),
                    "canonical_company_id": row.get("canonical_company_id"),
                    "name": row.get("name"),
                    "title": row.get("title"),
                    "internal": _leaf(row, "internal"),
                    "external": _leaf(row, "external"),
                    "decision": "both",
                    "note": None,
                }
            )

        # Apply explicit mark_same decisions
        for dec in decisions:
            if dec.decision_type != "mark_same":
                continue
            left_row = exec_map.get(dec.left_executive_id)
            right_row = exec_map.get(dec.right_executive_id)
            if not left_row or not right_row:
                continue
            used.update({dec.left_executive_id, dec.right_executive_id})

            def _assign(row: dict) -> tuple[Optional[dict], Optional[dict]]:
                provenance = (row.get("discovered_by") or row.get("source_label") or "").lower()
                if provenance == "internal":
                    return _leaf(row, "internal"), None
                if provenance == "external":
                    return None, _leaf(row, "external")
                # default: fall back to external if not claimed
                return None, _leaf(row, provenance or "external")

            internal_leaf, external_leaf = _assign(left_row)
            ext2_internal, ext2_external = _assign(right_row)
            internal_leaf = internal_leaf or ext2_internal
            external_leaf = external_leaf or ext2_external

            matched_or_both.append(
                {
                    "company_prospect_id": left_row.get("company_prospect_id") or right_row.get("company_prospect_id"),
                    "canonical_company_id": dec.canonical_company_id or left_row.get("canonical_company_id") or right_row.get("canonical_company_id"),
                    "name": left_row.get("name") or right_row.get("name"),
                    "title": left_row.get("title") or right_row.get("title"),
                    "internal": internal_leaf,
                    "external": external_leaf,
                    "decision": dec.decision_type,
                    "note": dec.note,
                }
            )

        internal_rows = [row for row in exec_rows if row.get("discovered_by") == "internal" and row.get("id") not in used]
        external_rows = [row for row in exec_rows if row.get("discovered_by") == "external" and row.get("id") not in used]

        # Candidate matches (name/title exact within same company key)
        for i_row in internal_rows:
            for e_row in external_rows:
                if _company_key(i_row) != _company_key(e_row):
                    continue
                name_match = (i_row.get("name_normalized") or "").lower() == (e_row.get("name_normalized") or "").lower()
                title_match = (i_row.get("title") or "").strip().lower() == (e_row.get("title") or "").strip().lower()
                if not name_match and not title_match:
                    continue
                dec = decision_map.get((i_row["id"], e_row["id"]))
                if dec and dec.decision_type == "keep_separate":
                    continue
                candidate_matches.append(
                    {
                        "company_prospect_id": i_row.get("company_prospect_id"),
                        "canonical_company_id": i_row.get("canonical_company_id") or e_row.get("canonical_company_id"),
                        "name": i_row.get("name") or e_row.get("name"),
                        "title": i_row.get("title") or e_row.get("title"),
                        "internal": _leaf(i_row, "internal"),
                        "external": _leaf(e_row, "external"),
                        "decision": dec.decision_type if dec else None,
                        "note": dec.note if dec else None,
                    }
                )

        used_internal = {row.get("id") for row in internal_rows}
        used_external = {row.get("id") for row in external_rows}
        used_internal -= {match["internal"]["id"] for match in candidate_matches if match.get("internal")}
        used_external -= {match["external"]["id"] for match in candidate_matches if match.get("external")}

        for row in sorted([r for r in internal_rows if r.get("id") in used_internal], key=lambda r: (r.get("name_normalized") or "").lower(), ):
            internal_only.append(_leaf(row, "internal"))
        for row in sorted([r for r in external_rows if r.get("id") in used_external], key=lambda r: (r.get("name_normalized") or "").lower(), ):
            external_only.append(_leaf(row, "external"))

        matched_or_both_sorted = sorted(
            matched_or_both,
            key=lambda r: ((r.get("company_prospect_id") or ""), (r.get("name") or "").lower(), r.get("title") or ""),
        )
        candidate_sorted = sorted(
            candidate_matches,
            key=lambda r: ((r.get("name") or "").lower(), r.get("title") or ""),
        )

        return {
            "matched_or_both": matched_or_both_sorted,
            "internal_only": internal_only,
            "external_only": external_only,
            "candidate_matches": candidate_sorted,
        }

    # ====================================================================
    # Export Pack (Phase 8.1)
    # ====================================================================

    async def _company_evidence_map(self, tenant_id: str, prospect_ids: List[UUID]) -> Dict[UUID, List[UUID]]:
        if not prospect_ids:
            return {}

        tenant_uuid = UUID(str(tenant_id))

        result = await self.db.execute(
            select(CompanyProspectEvidence)
            .where(
                CompanyProspectEvidence.tenant_id == tenant_uuid,
                CompanyProspectEvidence.company_prospect_id.in_(prospect_ids),
            )
            .order_by(
                CompanyProspectEvidence.company_prospect_id.asc(),
                CompanyProspectEvidence.created_at.asc(),
            )
        )

        evidence_map: Dict[UUID, List[UUID]] = defaultdict(list)
        for ev in result.scalars().all():
            if ev.source_document_id:
                evidence_map[ev.company_prospect_id].append(ev.source_document_id)

        return {pid: sorted({*ids}, key=lambda v: str(v)) for pid, ids in evidence_map.items()}

    async def _latest_exec_contact_enrichment_map(self, tenant_id: str, exec_ids: List[UUID]) -> Dict[UUID, dict]:
        if not exec_ids:
            return {}

        tenant_uuid = UUID(str(tenant_id))
        result = await self.db.execute(
            select(
                AIEnrichmentRecord.target_id,
                AIEnrichmentRecord.status,
                AIEnrichmentRecord.source_document_id,
                AIEnrichmentRecord.created_at,
            )
            .where(
                AIEnrichmentRecord.tenant_id == tenant_uuid,
                AIEnrichmentRecord.purpose == "executive_contact_enrichment",
                AIEnrichmentRecord.target_type == "EXECUTIVE",
                AIEnrichmentRecord.target_id.in_(exec_ids),
            )
            .order_by(
                AIEnrichmentRecord.target_id.asc(),
                AIEnrichmentRecord.created_at.desc(),
            )
        )

        mapping: Dict[UUID, dict] = {}
        for target_id, status, source_document_id, created_at in result.all():
            if target_id in mapping:
                continue
            mapping[target_id] = {
                "status": status,
                "source_document_id": source_document_id,
                "created_at": created_at,
            }
        return mapping

    async def _pipeline_map(self, tenant_id: str, exec_ids: List[UUID]) -> Dict[UUID, dict]:
        if not exec_ids:
            return {}

        tenant_uuid = UUID(str(tenant_id))
        exec_strings = [str(eid) for eid in exec_ids]
        payload_exec_id = ResearchEvent.raw_payload["executive_id"].astext

        result = await self.db.execute(
            select(
                payload_exec_id,
                ResearchEvent.entity_id,
                ResearchEvent.raw_payload["contact_id"].astext,
                ResearchEvent.raw_payload["assignment_id"].astext,
                ResearchEvent.raw_payload["role_mandate_id"].astext,
                ResearchEvent.raw_payload["pipeline_stage_id"].astext,
                ResearchEvent.raw_payload["pipeline_stage_name"].astext,
                ResearchEvent.raw_payload["assignment_status"].astext,
                ResearchEvent.created_at,
            )
            .where(
                ResearchEvent.tenant_id == tenant_uuid,
                ResearchEvent.source_type == "executive_review",
                ResearchEvent.entity_type == "CANDIDATE",
                payload_exec_id.in_(exec_strings),
            )
            .order_by(ResearchEvent.created_at.desc())
        )

        assignment_ids: List[UUID] = []
        mapping: Dict[UUID, dict] = {}
        raw_rows = result.all()
        for exec_id_text, candidate_id, contact_id_text, assignment_id_text, role_id_text, stage_id_text, stage_name_text, assignment_status_text, created_at in raw_rows:
            exec_uuid = UUID(str(exec_id_text))
            if exec_uuid in mapping:
                continue
            contact_uuid = None
            assignment_uuid = None
            try:
                contact_uuid = UUID(contact_id_text) if contact_id_text else None
            except (ValueError, TypeError):
                contact_uuid = None
            try:
                assignment_uuid = UUID(assignment_id_text) if assignment_id_text else None
            except (ValueError, TypeError):
                assignment_uuid = None
            if assignment_uuid:
                assignment_ids.append(assignment_uuid)
            mapping[exec_uuid] = {
                "candidate_id": candidate_id,
                "contact_id": contact_uuid,
                "assignment_id": assignment_uuid,
                "role_id": None,
                "pipeline_stage_id": None,
                "pipeline_stage_name": stage_name_text,
                "assignment_status": assignment_status_text,
                "created_at": created_at,
            }

        assignment_details: Dict[UUID, dict] = {}
        if assignment_ids:
            assignment_rows = await self.db.execute(
                select(
                    CandidateAssignment.id,
                    CandidateAssignment.role_id,
                    CandidateAssignment.current_stage_id,
                    CandidateAssignment.status,
                    PipelineStage.name,
                )
                .outerjoin(PipelineStage, PipelineStage.id == CandidateAssignment.current_stage_id)
                .where(CandidateAssignment.id.in_(assignment_ids))
            )
            for assignment_id, role_id, stage_id, status, stage_name in assignment_rows.all():
                assignment_details[assignment_id] = {
                    "role_id": role_id,
                    "stage_id": stage_id,
                    "status": status,
                    "stage_name": stage_name,
                }

        for exec_uuid, values in mapping.items():
            assignment_uuid = values.get("assignment_id")
            details = assignment_details.get(assignment_uuid) if assignment_uuid else None

            role_uuid = details.get("role_id") if details else None
            stage_uuid = details.get("stage_id") if details else None
            assignment_status = details.get("status") if details else None
            stage_name = details.get("stage_name") if details else None

            if not stage_uuid:
                raw_stage = next((row for row in raw_rows if UUID(str(row[0])) == exec_uuid), None)
                if raw_stage:
                    try:
                        stage_uuid = UUID(str(raw_stage[5])) if raw_stage[5] else None
                    except (ValueError, TypeError):
                        stage_uuid = None
                    stage_name = stage_name or raw_stage[6]

            if not role_uuid:
                raw_role = next((row for row in raw_rows if UUID(str(row[0])) == exec_uuid), None)
                if raw_role and raw_role[4]:
                    try:
                        role_uuid = UUID(str(raw_role[4]))
                    except (ValueError, TypeError):
                        role_uuid = None

            values["role_id"] = role_uuid
            values["pipeline_stage_id"] = stage_uuid
            values["pipeline_stage_name"] = stage_name
            values["assignment_status"] = assignment_status or values.get("assignment_status")
        return mapping

    def _build_pack_audit_summary(
        self,
        companies: List[PackCompany],
        executives: List[PackExecutive],
        pipeline_map: Dict[UUID, dict],
    ) -> PackAuditSummary:
        companies_total = len(companies)
        companies_accepted = sum(1 for c in companies if (c.review_status or "").lower() == "accepted")
        companies_hold = sum(1 for c in companies if (c.review_status or "").lower() == "hold")
        companies_rejected = sum(1 for c in companies if (c.review_status or "").lower() == "rejected")

        executives_total = len(executives)
        exec_accepted = sum(1 for e in executives if (e.review_status or "").lower() == "accepted")
        exec_hold = sum(1 for e in executives if (e.review_status or "").lower() == "hold")
        exec_rejected = sum(1 for e in executives if (e.review_status or "").lower() == "rejected")

        pipeline_created_count = len(pipeline_map)

        return PackAuditSummary(
            companies_total=companies_total,
            companies_accepted=companies_accepted,
            companies_hold=companies_hold,
            companies_rejected=companies_rejected,
            executives_total=executives_total,
            exec_accepted=exec_accepted,
            exec_hold=exec_hold,
            exec_rejected=exec_rejected,
            pipeline_created_count=pipeline_created_count,
            events=[],
        )

    def _serialize_pack_csvs(self, pack: RunPack) -> Dict[str, bytes]:
        files: Dict[str, bytes] = {}

        company_rows = io.StringIO()
        company_writer = csv.writer(company_rows)
        company_writer.writerow(
            [
                "company_prospect_id",
                "canonical_company_id",
                "name",
                "rank_position",
                "rank_score",
                "review_status",
                "verification_status",
                "discovered_by",
                "exec_search_enabled",
                "evidence_source_document_ids",
                "why_ranked_reason_codes",
            ]
        )
        for company in sorted(pack.companies, key=lambda c: (c.rank_position, str(c.company_prospect_id))):
            company_writer.writerow(
                [
                    company.company_prospect_id,
                    company.canonical_company_id,
                    company.name,
                    company.rank_position,
                    f"{float(company.rank_score):.6f}",
                    company.review_status,
                    company.verification_status,
                    company.discovered_by,
                    company.exec_search_enabled,
                    "|".join(str(eid) for eid in company.evidence_source_document_ids),
                    ";".join(company.why_ranked_reason_codes),
                ]
            )
        files["companies.csv"] = company_rows.getvalue().encode("utf-8")

        exec_rows = io.StringIO()
        exec_writer = csv.writer(exec_rows)
        exec_writer.writerow(
            [
                "company_prospect_id",
                "executive_id",
                "display_name",
                "title",
                "provenance",
                "verification_status",
                "review_status",
                "rank_position",
                "rank_score",
                "pipeline_status",
                "candidate_id",
                "contact_id",
                "contact_enrichment_status",
                "contact_enrichment_source_document_id",
                "evidence_source_document_ids",
            ]
        )

        exec_list: List[PackExecutive] = []
        for _, execs in sorted(pack.executives_by_company.items(), key=lambda pair: pair[0]):
            exec_list.extend(execs)

        exec_sorted = sorted(
            exec_list,
            key=lambda e: (
                e.company_prospect_id,
                e.rank_position if e.rank_position is not None else 10 ** 9,
                str(e.executive_id),
            ),
        )

        for exec_item in exec_sorted:
            exec_writer.writerow(
                [
                    exec_item.company_prospect_id,
                    exec_item.executive_id,
                    exec_item.display_name,
                    exec_item.title or "",
                    exec_item.provenance or "",
                    exec_item.verification_status or "",
                    exec_item.review_status or "",
                    exec_item.rank_position,
                    f"{float(exec_item.rank_score):.6f}" if exec_item.rank_score is not None else "",
                    exec_item.pipeline_status,
                    exec_item.candidate_id,
                    exec_item.contact_id,
                    exec_item.contact_enrichment_status or "",
                    exec_item.contact_enrichment_source_document_id,
                    "|".join(str(eid) for eid in exec_item.evidence_source_document_ids),
                ]
            )
        files["executives.csv"] = exec_rows.getvalue().encode("utf-8")

        merge_rows = io.StringIO()
        merge_writer = csv.writer(merge_rows)
        merge_writer.writerow(
            [
                "decision_id",
                "company_prospect_id",
                "canonical_company_id",
                "left_executive_id",
                "right_executive_id",
                "action",
                "decided_by",
                "evidence_source_document_ids",
                "evidence_enrichment_ids",
            ]
        )
        for decision in sorted(pack.merge_decisions, key=lambda d: (str(d.company_prospect_id or ""), str(d.decision_id))):
            merge_writer.writerow(
                [
                    decision.decision_id,
                    decision.company_prospect_id,
                    decision.canonical_company_id,
                    decision.left_executive_id,
                    decision.right_executive_id,
                    decision.action,
                    decision.decided_by,
                    "|".join(str(eid) for eid in decision.evidence_source_document_ids),
                    "|".join(str(eid) for eid in decision.evidence_enrichment_ids),
                ]
            )
        files["merge_decisions.csv"] = merge_rows.getvalue().encode("utf-8")

        audit_rows = io.StringIO()
        audit_writer = csv.writer(audit_rows)
        audit_writer.writerow(["metric", "value"])
        audit = pack.audit_summary
        audit_writer.writerow(["companies_total", audit.companies_total])
        audit_writer.writerow(["companies_accepted", audit.companies_accepted])
        audit_writer.writerow(["companies_hold", audit.companies_hold])
        audit_writer.writerow(["companies_rejected", audit.companies_rejected])
        audit_writer.writerow(["executives_total", audit.executives_total])
        audit_writer.writerow(["exec_accepted", audit.exec_accepted])
        audit_writer.writerow(["exec_hold", audit.exec_hold])
        audit_writer.writerow(["exec_rejected", audit.exec_rejected])
        audit_writer.writerow(["pipeline_created_count", audit.pipeline_created_count])
        files["audit_summary.csv"] = audit_rows.getvalue().encode("utf-8")

        return files

    def _serialize_pack_html(self, pack: RunPack) -> bytes:
        companies_sorted = sorted(pack.companies, key=lambda c: (c.rank_position, str(c.company_prospect_id)))

        def esc(value: Any) -> str:
            return str(value or "")

        lines: List[str] = []
        lines.append("<html><head><style>body{font-family:Arial,sans-serif;}table{border-collapse:collapse;width:100%;margin-bottom:16px;}th,td{border:1px solid #ccc;padding:6px;font-size:12px;}th{background:#f5f5f5;text-align:left;}h2{margin:12px 0 4px;}small{color:#666;}</style></head><body>")
        lines.append(f"<h1>Export Pack for Run {pack.run_id}</h1>")
        lines.append(f"<p>Tenant: {pack.tenant_id}</p>")

        lines.append("<h2>Companies</h2>")
        lines.append("<table><thead><tr><th>Rank</th><th>Name</th><th>Review</th><th>Verification</th><th>Evidence IDs</th></tr></thead><tbody>")
        for company in companies_sorted:
            lines.append(
                "<tr>"
                f"<td>{company.rank_position}</td>"
                f"<td>{esc(company.name)}</td>"
                f"<td>{esc(company.review_status)}</td>"
                f"<td>{esc(company.verification_status)}</td>"
                f"<td>{'|'.join(str(eid) for eid in company.evidence_source_document_ids)}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")

        lines.append("<h2>Executives</h2>")
        for company in companies_sorted:
            execs = pack.executives_by_company.get(str(company.company_prospect_id), [])
            if not execs:
                continue
            lines.append(f"<h3>{esc(company.name)} (rank {company.rank_position})</h3>")
            lines.append("<table><thead><tr><th>Rank</th><th>Name</th><th>Title</th><th>Review</th><th>Pipeline</th><th>Contact Enrichment</th></tr></thead><tbody>")
            for exec_item in sorted(
                execs,
                key=lambda e: (
                    e.rank_position if e.rank_position is not None else 10 ** 9,
                    str(e.executive_id),
                ),
            ):
                lines.append(
                    "<tr>"
                    f"<td>{esc(exec_item.rank_position)}</td>"
                    f"<td>{esc(exec_item.display_name)}</td>"
                    f"<td>{esc(exec_item.title)}</td>"
                    f"<td>{esc(exec_item.review_status)}</td>"
                    f"<td>{esc(exec_item.pipeline_status)}</td>"
                    f"<td>{esc(exec_item.contact_enrichment_status)}</td>"
                    "</tr>"
                )
            lines.append("</tbody></table>")

        lines.append("</body></html>")
        return "\n".join(lines).encode("utf-8")

    async def build_run_export_pack(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        include_html: bool = False,
        max_companies: Optional[int] = None,
        max_executives: Optional[int] = None,
    ) -> Tuple[RunPack, bytes, Dict[str, bytes]]:
        run = await self.get_research_run(tenant_id, run_id)
        if not run:
            raise ValueError("research_run_not_found")

        company_limit = max_companies or self.EXPORT_DEFAULT_MAX_COMPANIES
        exec_limit = max_executives or self.EXPORT_DEFAULT_MAX_EXECUTIVES

        if company_limit < 1 or exec_limit < 1:
            raise ValueError("export_param_invalid")

        company_limit = min(company_limit, self.EXPORT_MAX_COMPANIES)
        exec_limit = min(exec_limit, self.EXPORT_MAX_EXECUTIVES)

        prospect_count = await self.count_prospects_for_run(tenant_id, run_id)
        if prospect_count:
            company_limit = min(company_limit, prospect_count)

        ranked_companies = await self.rank_prospects_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            status=None,
            min_relevance_score=None,
            limit=company_limit,
            offset=0,
        )

        company_ids = [UUID(str(item.get("id"))) for item in ranked_companies]
        evidence_map = await self._company_evidence_map(tenant_id, company_ids)

        pack_companies: List[PackCompany] = []
        for idx, company_item in enumerate(ranked_companies, start=1):
            evidence_ids = evidence_map.get(UUID(str(company_item.get("id"))), [])
            why_codes = []
            for signal in company_item.get("why_included") or []:
                code = getattr(signal, "field_key", None) or getattr(signal, "field_name", None)
                if code:
                    why_codes.append(str(code))

            pack_companies.append(
                PackCompany(
                    company_prospect_id=UUID(str(company_item["id"])),
                    canonical_company_id=company_item.get("normalized_company_id"),
                    name=company_item.get("name_normalized") or company_item.get("name_raw") or "",
                    rank_position=idx,
                    rank_score=float(company_item.get("computed_score", 0.0)),
                    review_status=company_item.get("review_status"),
                    verification_status=company_item.get("verification_status"),
                    discovered_by=company_item.get("discovered_by"),
                    exec_search_enabled=company_item.get("exec_search_enabled"),
                    evidence_source_document_ids=evidence_ids,
                    why_ranked_reason_codes=sorted({code for code in why_codes}),
                )
            )

        ranked_executives = await self.rank_executives_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            company_prospect_id=None,
            provenance=None,
            verification_status=None,
            q=None,
            limit=exec_limit,
            offset=0,
        )

        exec_ids = [UUID(str(item["executive_id"])) for item in ranked_executives]
        exec_rows = await self.list_executive_prospects_with_evidence(
            tenant_id=tenant_id,
            run_id=run_id,
            canonical_company_id=None,
            company_prospect_id=None,
            discovered_by=None,
            verification_status=None,
        )
        exec_map: Dict[UUID, dict] = {UUID(str(row["id"])): row for row in exec_rows}

        contact_map = await self._latest_exec_contact_enrichment_map(tenant_id, exec_ids)
        pipeline_map = await self._pipeline_map(tenant_id, exec_ids)

        executives_by_company: Dict[str, List[PackExecutive]] = defaultdict(list)
        flat_execs: List[PackExecutive] = []

        for exec_item in ranked_executives:
            exec_id = UUID(str(exec_item["executive_id"]))
            company_id = UUID(str(exec_item["company_prospect_id"]))
            exec_row = exec_map.get(exec_id, {})
            evidence_ids = exec_row.get("evidence_source_document_ids") or []
            enrichment_info = contact_map.get(exec_id)
            pipeline_info = pipeline_map.get(exec_id)

            pack_exec = PackExecutive(
                executive_id=exec_id,
                company_prospect_id=company_id,
                display_name=exec_item.get("display_name") or "",
                title=exec_item.get("title"),
                provenance=exec_item.get("provenance") or exec_row.get("provenance"),
                verification_status=exec_item.get("verification_status") or exec_row.get("verification_status"),
                review_status=exec_row.get("review_status"),
                rank_position=exec_item.get("rank_position"),
                rank_score=float(exec_item.get("rank_score", 0.0)),
                pipeline_status="created" if pipeline_info else "not_created",
                candidate_id=pipeline_info.get("candidate_id") if pipeline_info else None,
                contact_id=pipeline_info.get("contact_id") if pipeline_info else None,
                role_id=pipeline_info.get("role_id") if pipeline_info else None,
                assignment_id=pipeline_info.get("assignment_id") if pipeline_info else None,
                assignment_status=pipeline_info.get("assignment_status") if pipeline_info else None,
                pipeline_stage_id=pipeline_info.get("pipeline_stage_id") if pipeline_info else None,
                pipeline_stage_name=pipeline_info.get("pipeline_stage_name") if pipeline_info else None,
                contact_enrichment_status=(enrichment_info or {}).get("status"),
                contact_enrichment_source_document_id=(enrichment_info or {}).get("source_document_id"),
                evidence_source_document_ids=sorted({UUID(str(eid)) for eid in evidence_ids if eid}, key=lambda v: str(v)),
            )

            executives_by_company[str(company_id)].append(pack_exec)
            flat_execs.append(pack_exec)

        decisions = await self.repo.list_merge_decisions_for_run(tenant_id, run_id)
        pack_decisions: List[PackMergeDecision] = []
        for dec in decisions:
            pack_decisions.append(
                PackMergeDecision(
                    decision_id=dec.id,
                    company_prospect_id=dec.company_prospect_id,
                    canonical_company_id=dec.canonical_company_id,
                    left_executive_id=dec.left_executive_id,
                    right_executive_id=dec.right_executive_id,
                    action=dec.decision_type,  # mark_same | keep_separate
                    decided_by=dec.created_by,
                    evidence_source_document_ids=sorted({UUID(str(e)) for e in (dec.evidence_source_document_ids or [])}, key=lambda v: str(v)),
                    evidence_enrichment_ids=sorted({UUID(str(e)) for e in (dec.evidence_enrichment_ids or [])}, key=lambda v: str(v)),
                )
            )

        audit_summary = self._build_pack_audit_summary(pack_companies, flat_execs, pipeline_map)

        pack = RunPack(
            run_id=run_id,
            tenant_id=tenant_id,
            generated_at=None,  # excluded from export for determinism
            companies=pack_companies,
            executives_by_company={key: value for key, value in sorted(executives_by_company.items(), key=lambda pair: pair[0])},
            merge_decisions=sorted(pack_decisions, key=lambda d: (str(d.company_prospect_id or ""), str(d.decision_id))),
            audit_summary=audit_summary,
        )

        pack_json_bytes = json.dumps(pack.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode("utf-8")
        files = self._serialize_pack_csvs(pack)
        files["run_pack.json"] = pack_json_bytes

        if include_html:
            files["print_view.html"] = self._serialize_pack_html(pack)

        readme = [
            "Export pack contents:",
            "- run_pack.json",
            "- companies.csv",
            "- executives.csv",
            "- merge_decisions.csv",
            "- audit_summary.csv",
        ]
        if include_html:
            readme.append("- print_view.html")
        files["README.txt"] = "\n".join(readme).encode("utf-8")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(files.keys()):
                zf.writestr(name, files[name])

        zip_bytes = zip_buffer.getvalue()
        if len(zip_bytes) > self.EXPORT_MAX_ZIP_BYTES:
            raise ValueError("export_pack_too_large")

        return pack, zip_bytes, files

    async def apply_executive_merge_decision(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        decision_type: str,
        left_executive_id: UUID,
        right_executive_id: UUID,
        note: Optional[str],
        evidence_source_document_ids: list[UUID] | None,
        evidence_enrichment_ids: list[UUID] | None,
        actor: Optional[str] = None,
    ) -> tuple[ExecutiveMergeDecision, bool]:
        if decision_type not in {"mark_same", "keep_separate"}:
            raise ValueError("invalid_decision_type")

        left = await self.repo.get_executive_prospect(tenant_id, left_executive_id)
        right = await self.repo.get_executive_prospect(tenant_id, right_executive_id)
        if not left or not right:
            raise ValueError("executive_not_found")
        if left.company_research_run_id != run_id or right.company_research_run_id != run_id:
            raise ValueError("run_mismatch")

        company_prospect_id = left.company_prospect_id if left.company_prospect_id == right.company_prospect_id else None
        canonical_company_id = None
        if company_prospect_id:
            canonical_company_id = getattr(left.company_prospect, "normalized_company_id", None)
        else:
            canonical_company_id = getattr(left, "canonical_company_id", None) or getattr(right, "canonical_company_id", None)

        decision, created = await self.repo.upsert_merge_decision(
            tenant_id=tenant_id,
            run_id=run_id,
            company_prospect_id=company_prospect_id,
            canonical_company_id=canonical_company_id,
            left_executive_id=left_executive_id,
            right_executive_id=right_executive_id,
            decision_type=decision_type,
            note=note,
            evidence_source_document_ids=evidence_source_document_ids,
            evidence_enrichment_ids=evidence_enrichment_ids,
            created_by=actor,
        )

        if decision_type == "mark_same":
            merged_provenance = self._merge_provenance(
                getattr(left, "discovered_by", None),
                getattr(right, "discovered_by", None),
            )
            left.discovered_by = merged_provenance
            right.discovered_by = merged_provenance
            left.source_label = self._merge_provenance(getattr(left, "source_label", None), getattr(right, "source_label", None))
            right.source_label = self._merge_provenance(getattr(right, "source_label", None), getattr(left, "source_label", None))

            promoted = self._promote_verification(
                getattr(left, "verification_status", "unverified"),
                getattr(right, "verification_status", "unverified"),
            )
            left.verification_status = promoted
            right.verification_status = promoted

        if created:
            evidence_docs = ",".join([str(eid) for eid in (decision.evidence_source_document_ids or [])]) or "none"
            evidence_enrich = ",".join([str(eid) for eid in (decision.evidence_enrichment_ids or [])]) or "none"
            self.db.add(
                ActivityLog(
                    tenant_id=tenant_id,
                    role_id=getattr(left.company_prospect, "role_mandate_id", None) if getattr(left, "company_prospect", None) else None,
                    type="EXEC_COMPARE_DECISION",
                    message=(
                        f"run_id={run_id} decision={decision_type} left={left_executive_id} right={right_executive_id} "
                        f"company_prospect_id={company_prospect_id} canonical_company_id={canonical_company_id} "
                        f"evidence_docs={evidence_docs} enrichment_ids={evidence_enrich}"
                    ),
                    created_by=actor or "system",
                )
            )

        await self.db.flush()
        await self.db.refresh(decision)
        return decision, created
    
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
        """Normalize URLs by stripping whitespace and ensuring scheme present."""
        if not url:
            return None
        cleaned = url.strip()
        if not cleaned:
            return None
        parsed = urlparse(cleaned)
        if not parsed.scheme:
            parsed = parsed._replace(scheme="https")
        normalized = parsed._replace(fragment="", query="")
        return urlunparse(normalized)

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
    def _normalize_seed_raw_text(raw_text: Optional[str]) -> str:
        """Normalize raw seed payload text for stable hashing."""
        if raw_text is None:
            return ""
        normalized = "\n".join(str(raw_text).splitlines()).strip()
        return normalized

    @staticmethod
    def _normalize_person_name(name: Optional[str]) -> str:
        if not name:
            return ""
        lowered = name.lower()
        cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
        return " ".join(cleaned.split())

    @staticmethod
    def _merge_discovered_by(existing: Optional[str], incoming: str) -> str:
        """Combine discovery provenance into a compact label."""
        if not existing:
            return incoming
        if existing == incoming or existing == "both":
            return existing
        return "both"

    @staticmethod
    def _merge_provenance(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
        if not incoming:
            return existing
        if not existing:
            return incoming
        if existing == incoming or existing == "both" or incoming == "both":
            return "both" if existing == "both" or incoming == "both" else existing
        return "both"

    @staticmethod
    def _promote_verification(current: Optional[str], incoming: Optional[str]) -> str:
        order = ["unverified", "partial", "verified"]
        cur = current or "unverified"
        inc = incoming or cur
        try:
            return cur if order.index(cur) >= order.index(inc) else inc
        except ValueError:
            return cur
    
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

        summary = await self._ingest_discovery_payload(
            tenant_id=tenant_id,
            run_id=run_id,
            source=source,
            parsed_payload=parsed,
            provider=provider,
            model_name=model_name,
            content_hash=content_hash,
            purpose=purpose,
        )

        return summary

    async def run_discovery_provider(
        self,
        tenant_id: str,
        run_id: UUID,
        provider_key: str,
        request_payload: Optional[dict] = None,
        purpose: str = "company_discovery",
    ) -> dict:
        """Run a registered discovery provider and ingest its output idempotently."""

        if purpose != "company_discovery":
            raise ValueError("invalid_purpose")

        provider = get_discovery_provider(provider_key)
        if not provider:
            raise ValueError("unknown_provider")

        # Enforce run existence and mutability before generating provider output
        await self.ensure_sources_unlocked(tenant_id, run_id)

        provider_request = request_payload or {}
        if hasattr(provider_request, "model_dump"):
            provider_request = provider_request.model_dump(exclude_none=True)

        provider_result = provider.run(
            tenant_id=tenant_id,
            run_id=run_id,
            request=provider_request,
        )

        raw_source = None
        raw_hash = None
        if provider_result.raw_input_text:
            normalized_raw = self._normalize_seed_raw_text(provider_result.raw_input_text)
            raw_hash = hashlib.sha256(normalized_raw.encode("utf-8")).hexdigest()
            existing_raw = await self.repo.find_source_by_hash(tenant_id, run_id, raw_hash)
            if existing_raw:
                raw_source = existing_raw
            else:
                raw_source = await self.add_source(
                    tenant_id,
                    SourceDocumentCreate(
                        company_research_run_id=run_id,
                        source_type="seed_input",
                        title=f"Seed input ({provider_result.provider})",
                        mime_type="text/plain",
                        content_text=normalized_raw,
                        content_hash=raw_hash,
                        meta={
                            "kind": "seed_input",
                            "provider": provider_result.provider,
                            "version": provider_result.version,
                            **(provider_result.raw_input_meta or {}),
                        },
                    ),
                )
            raw_source.status = "processed"
            raw_source.error_message = None
            raw_source.meta = {**(raw_source.meta or {}), "ingest_stats": {"stored_raw": True}}
            await self.db.flush()

        raw_source_id = str(raw_source.id) if raw_source else None

        parsed = provider_result.payload
        canonical_json = self._canonical_json(parsed.canonical_dict())
        content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        existing_source = await self.repo.find_source_by_hash(tenant_id, run_id, content_hash)
        if existing_source:
            enrichment_query = await self.db.execute(
                select(AIEnrichmentRecord).where(
                    AIEnrichmentRecord.tenant_id == tenant_id,
                    AIEnrichmentRecord.company_research_run_id == run_id,
                    AIEnrichmentRecord.purpose == purpose,
                    AIEnrichmentRecord.provider == provider_result.provider,
                    AIEnrichmentRecord.content_hash == content_hash,
                )
            )
            enrichment = enrichment_query.scalar_one_or_none()
            ingest_meta = (existing_source.meta or {}).get("ingest_stats")
            return {
                "skipped": True,
                "reason": "duplicate_hash",
                "source_id": str(existing_source.id),
                "enrichment_id": str(enrichment.id) if enrichment else (existing_source.meta or {}).get("enrichment_id"),
                "ingest_stats": ingest_meta,
                "provider_version": provider_result.version,
                "content_hash": content_hash,
                "raw_source_id": raw_source_id,
            }

        source_meta = {
            "kind": "discovery_provider",
            "provider": provider_result.provider,
            "version": provider_result.version,
            "model": provider_result.model,
            "purpose": purpose,
            "schema_version": parsed.schema_version,
            "raw_source_id": raw_source_id,
        }

        source = await self.add_source(
            tenant_id,
            SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="discovery_provider",
                title=f"Discovery provider: {provider_key}",
                mime_type="application/json",
                content_text=canonical_json,
                content_hash=content_hash,
                meta=source_meta,
            ),
        )

        summary = await self._ingest_discovery_payload(
            tenant_id=tenant_id,
            run_id=run_id,
            source=source,
            parsed_payload=parsed,
            provider=provider_result.provider,
            model_name=provider_result.model,
            content_hash=content_hash,
            purpose=purpose,
        )

        return {**summary, "provider_version": provider_result.version, "raw_source_id": raw_source_id, "content_hash": content_hash}

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
                summary = await self._ingest_discovery_payload(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    source=src,
                    parsed_payload=parsed,
                    provider=(src.meta or {}).get("provider") or payload_dict.get("provider") or "mock",
                    model_name=(src.meta or {}).get("model") or payload_dict.get("model"),
                    content_hash=content_hash,
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

    async def _ingest_discovery_payload(
        self,
        tenant_id: str,
        run_id: UUID,
        source: ResearchSourceDocument,
        parsed_payload: LlmDiscoveryPayload,
        provider: str,
        model_name: Optional[str],
        content_hash: str,
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

        discovery_label = provider or "grok"

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

        # Track evidence we have already attached for a given company and discovery source to avoid
        # violating the unique constraint (tenant_id, company_prospect_id, source_document_id, source_type, source_name).
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
                # Align dedupe with DB uniqueness: scope on company + source doc + name/type, not URL
                dedupe_key = (
                    str(existing.id),
                    str(source.id),
                    (ev.label or ev.kind or "llm_json"),
                )
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

    def _merge_provenance(self, current: Optional[str], incoming: str) -> str:
        cur = (current or "").lower()
        inc = (incoming or "").lower()
        if not cur:
            return incoming
        if cur == inc:
            return cur
        if cur == "both" or inc == "both":
            return "both"
        return "both"

    def _promote_verification(self, current: Optional[str], incoming: Optional[str]) -> str:
        order = ["unverified", "partial", "verified"]
        cur = (current or "unverified").lower()
        inc = (incoming or cur).lower()
        cur = cur if cur in order else "unverified"
        inc = inc if inc in order else cur
        return inc if order.index(inc) > order.index(cur) else cur

    async def ingest_executive_llm_json_payload(
        self,
        tenant_id: str,
        run_id: UUID,
        payload: dict,
        provider: str,
        model_name: Optional[str],
        title: Optional[str],
        engine: str = "external",
        request_payload: Optional[dict] = None,
    ) -> dict:
        """Ingest executive discovery payload with gating and idempotency."""
        parsed = ExecutiveDiscoveryPayload(**payload)
        response_canonical = self._canonical_json(parsed.canonical_dict())

        req_payload = request_payload or payload
        if isinstance(req_payload, ExecutiveDiscoveryPayload):
            request_canonical = self._canonical_json(req_payload.canonical_dict())
        else:
            request_canonical = self._canonical_json(req_payload)

        response_hash = hashlib.sha256(f"{engine}:response:{response_canonical}".encode("utf-8")).hexdigest()
        request_hash = hashlib.sha256(f"{engine}:request:{request_canonical}".encode("utf-8")).hexdigest()

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

        existing_request_source = await self.repo.find_source_by_hash(tenant_id, run_id, request_hash)
        existing_response_source = await self.repo.find_source_by_hash(tenant_id, run_id, response_hash)

        enrichment_query = await self.db.execute(
            select(AIEnrichmentRecord).where(
                AIEnrichmentRecord.tenant_id == tenant_id,
                AIEnrichmentRecord.company_research_run_id == run_id,
                AIEnrichmentRecord.purpose == "executive_discovery",
                AIEnrichmentRecord.provider == provider,
                AIEnrichmentRecord.content_hash == response_hash,
            )
        )
        enrichment = enrichment_query.scalar_one_or_none()
        if enrichment and existing_response_source:
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
                "source_id": str(existing_response_source.id),
                "request_source_id": str(existing_request_source.id) if existing_request_source else None,
                "enrichment_id": str(enrichment.id),
                "ingest_stats": ingest_meta,
                "eligible_company_count": len(eligible),
                "processed_company_count": len(requested_companies),
                "company_summaries": [],
            }

        existing_sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        url_norm_map = {self._normalize_url_value(s.url): s for s in existing_sources if s.url}

        request_source = existing_request_source or await self.add_source(
            tenant_id,
            SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="llm_json",
                title=title or f"{engine} executive discovery request",
                mime_type="application/json",
                content_text=request_canonical,
                content_hash=request_hash,
                meta={
                    "kind": "llm_json_request",
                    "purpose": "executive_discovery",
                    "engine": engine,
                    "provider": provider,
                    "model": model_name,
                },
            ),
        )

        response_source = existing_response_source or await self.add_source(
            tenant_id,
            SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="llm_json",
                title=title or f"{engine} executive discovery response",
                mime_type="application/json",
                content_text=response_canonical,
                content_hash=response_hash,
                meta={
                    "kind": "llm_json_response",
                    "purpose": "executive_discovery",
                    "engine": engine,
                    "provider": provider,
                    "model": model_name,
                    "request_source_id": str(request_source.id),
                },
            ),
        )

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
                input_scope_hash=request_hash,
                content_hash=response_hash,
                source_document_id=response_source.id,
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

        company_stats: dict[UUID, dict[str, object]] = {}
        evidence_seen: set[tuple[str, str, str, str]] = set()

        for company in parsed.companies:
            norm = self._normalize_company_name(company.company_normalized or company.company_name)
            if not norm:
                continue
            prospect = eligible_map.get(norm)
            if not prospect:
                continue

            company_entry = company_stats.setdefault(
                prospect.id,
                {
                    "company_prospect_id": str(prospect.id),
                    "company_name": prospect.name_normalized,
                    "executives_new": 0,
                    "executives_existing": 0,
                    "evidence_created": 0,
                    "engine": engine,
                },
            )

            for exec_entry in company.executives or []:
                exec_norm = self._normalize_person_name(exec_entry.name)
                if not exec_norm:
                    continue

                existing_exec = existing_exec_map.get(prospect.id, {}).get(exec_norm)
                if existing_exec:
                    stats["executives_existing"] += 1
                    company_entry["executives_existing"] += 1
                    target_exec = existing_exec
                    target_exec.discovered_by = self._merge_provenance(target_exec.discovered_by, engine)
                    target_exec.source_label = self._merge_provenance(target_exec.source_label, engine)
                    target_exec.verification_status = self._promote_verification(
                        target_exec.verification_status,
                        getattr(prospect, "verification_status", None),
                    )
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
                        source_label=engine,
                        source_document_id=response_source.id,
                        discovered_by=engine,
                        verification_status=getattr(prospect, "verification_status", "unverified") or "unverified",
                    )
                    self.db.add(target_exec)
                    await self.db.flush()
                    existing_exec_map[prospect.id][exec_norm] = target_exec
                    stats["executives_new"] += 1
                    company_entry["executives_new"] += 1

                for ev in exec_entry.evidence or []:
                    dedupe_key = (
                        str(target_exec.id),
                        engine,
                        ev.url or "",
                        ev.label or ev.kind or "executive_llm_json",
                    )
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
                        source_document_id=response_source.id,
                        source_content_hash=response_hash,
                    )
                    self.db.add(evidence)
                    stats["evidence_created"] += 1
                    company_entry["evidence_created"] += 1

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
                                    "llm_source_id": str(response_source.id),
                                    "evidence_kind": ev.kind,
                                    "evidence_label": ev.label,
                                    "engine": engine,
                                },
                            ),
                        )
                        url_norm_map[url_norm] = url_source
                        stats["urls_created"] += 1

        response_source.status = "processed"
        response_source.error_message = None
        response_source.meta = {
            **(response_source.meta or {}),
            "ingest_stats": stats,
            "enrichment_id": str(enrichment.id),
            "request_source_id": str(request_source.id),
        }

        await self.db.flush()

        return {
            "source_id": str(response_source.id),
            "request_source_id": str(request_source.id),
            "enrichment_id": str(enrichment.id),
            "content_hash": response_hash,
            "eligible_company_count": len(eligible),
            "processed_company_count": len(requested_companies),
            "company_summaries": list(company_stats.values()),
            **stats,
        }

    async def run_internal_executive_discovery(
        self,
        tenant_id: str,
        run_id: UUID,
        provider: str = "internal_stub",
        model_name: str = "deterministic_stub_v1",
    ) -> dict:
        """Run deterministic internal executive discovery over eligible companies."""

        eligible_unsorted = await self.list_executive_eligible_companies(tenant_id, run_id)
        eligible = sorted(
            eligible_unsorted,
            key=lambda p: self._normalize_company_name(p.name_normalized or p.name_raw) or "",
        )
        if not eligible:
            return {
                "skipped": True,
                "reason": "no_eligible_companies",
                "eligible_company_count": 0,
                "processed_company_count": 0,
                "company_summaries": [],
            }

        companies_payload: list[dict[str, object]] = []
        for prospect in eligible:
            company_name = prospect.name_normalized or prospect.name_raw
            company_norm = self._normalize_company_name(company_name)
            slug = re.sub(r"[^a-z0-9]+", "-", company_norm.lower()).strip("-") or "company"
            website = self._normalize_url_value(prospect.website_url or f"https://example.com/{slug}")
            location = prospect.hq_city or "Unknown"

            executives = [
                {
                    "name": f"{company_name} CEO",
                    "title": "Chief Executive Officer",
                    "profile_url": f"https://example.com/{slug}/ceo",
                    "linkedin_url": f"https://www.linkedin.com/in/{slug}-ceo",
                    "email": None,
                    "location": location,
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "url": website,
                            "label": "Internal stub leadership page",
                            "kind": "internal_stub",
                            "snippet": f"Leadership listing for {company_name} CEO.",
                        }
                    ],
                },
                {
                    "name": f"{company_name} CFO",
                    "title": "Chief Financial Officer",
                    "profile_url": f"https://example.com/{slug}/cfo",
                    "linkedin_url": f"https://www.linkedin.com/in/{slug}-cfo",
                    "email": None,
                    "location": location,
                    "confidence": 0.85,
                    "evidence": [
                        {
                            "url": website,
                            "label": "Internal stub leadership page",
                            "kind": "internal_stub",
                            "snippet": f"Finance lead reference for {company_name} CFO.",
                        }
                    ],
                },
            ]

            companies_payload.append(
                {
                    "company_name": company_name,
                    "company_normalized": company_norm,
                    "company_website": website,
                    "executives": executives,
                }
            )

        payload = {
            "schema_version": "executive_discovery_v1",
            "provider": provider,
            "model": model_name,
            # Fixed timestamp keeps content_hash stable across replays for idempotency.
            "generated_at": "1970-01-01T00:00:00+00:00",
            "query": f"deterministic_internal_stub:{run_id}",
            "companies": companies_payload,
        }

        ingest_result = await self.ingest_executive_llm_json_payload(
            tenant_id=tenant_id,
            run_id=run_id,
            payload=payload,
            provider=provider,
            model_name=model_name,
            title="Internal Executive Discovery",
            engine="internal",
            request_payload=payload,
        )

        return {
            **ingest_result,
            "eligible_company_count": len(eligible),
            "processed_company_count": len(companies_payload),
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
    # Entity Resolution (Stage 6.1)
    # ========================================================================

    async def run_entity_resolution_step(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Resolve run-scoped executive duplicates with evidence-first merges."""

        entity_type = "executive"
        resolver = EntityResolutionService(self.db)

        resolved_before = await self.repo.list_resolved_entities_for_run(
            tenant_id,
            run_id,
            entity_type=entity_type,
        )
        links_before = await self.repo.list_entity_merge_links_for_run(
            tenant_id,
            run_id,
            entity_type=entity_type,
        )

        try:
            summary = await resolver.resolve_run_entities(
                tenant_id=tenant_id,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="entity_resolution",
                    status="failed",
                    input_json={"stage": "6.1_entity_resolution", "entity_type": entity_type},
                    output_json=None,
                    error_message=f"{type(exc).__name__}: {exc}",
                ),
            )
            raise

        resolved_after = await self.repo.list_resolved_entities_for_run(
            tenant_id,
            run_id,
            entity_type=entity_type,
        )
        links_after = await self.repo.list_entity_merge_links_for_run(
            tenant_id,
            run_id,
            entity_type=entity_type,
        )

        resolved_new = max(len(resolved_after) - len(resolved_before), 0)
        links_new = max(len(links_after) - len(links_before), 0)

        enriched_summary = {
            "stage": "6.1_entity_resolution",
            "entity_type": entity_type,
            "inputs_considered": summary.get("executives_scanned", 0),
            "resolved_entities_total": len(resolved_after),
            "resolved_entities_new": resolved_new,
            "resolved_entities_existing": len(resolved_before),
            "merge_links_total": len(links_after),
            "merge_links_new": links_new,
            "merge_links_existing": len(links_before),
            **summary,
        }

        status = "ok"
        if summary.get("skipped"):
            status = "ok"

        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="entity_resolution",
                status=status,
                input_json={
                    "stage": "6.1_entity_resolution",
                    "entity_type": entity_type,
                    "executives_scanned": summary.get("executives_scanned", 0),
                },
                output_json=enriched_summary,
            ),
        )

        return enriched_summary

    async def list_resolved_entities_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: Optional[str] = None,
    ) -> List:
        """List resolved entities for a run (deterministic ordering)."""
        resolver = EntityResolutionService(self.db)
        return await resolver.list_resolved_entities(tenant_id, run_id, entity_type=entity_type)

    async def list_entity_merge_links_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: Optional[str] = None,
    ) -> List:
        """List entity merge links for a run (deterministic ordering)."""
        resolver = EntityResolutionService(self.db)
        return await resolver.list_entity_merge_links(tenant_id, run_id, entity_type=entity_type)

    # ========================================================================
    # Canonical People Resolution (Stage 6.2)
    # ========================================================================

    async def run_canonical_people_resolution_step(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Resolve tenant-wide canonical people with evidence-first linking."""

        resolver = CanonicalPeopleService(self.db)
        summary = await resolver.resolve_run_people(tenant_id=tenant_id, run_id=run_id)

        enriched_summary = {
            "stage": "6.2_canonical_people",
            "entity_type": "executive",
            **summary,
        }

        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="canonical_people_resolution",
                status="ok",
                input_json={"stage": "6.2_canonical_people", "entity_type": "executive"},
                output_json=enriched_summary,
            ),
        )

        return enriched_summary

    async def list_canonical_people(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ):
        records = await self.repo.list_canonical_people_with_counts(tenant_id, limit=limit, offset=offset)
        results = []
        for person, count in records:
            results.append({
                "person": person,
                "linked_entities_count": int(count or 0),
            })
        return results

    async def get_canonical_person_detail(
        self,
        tenant_id: str,
        canonical_person_id: UUID,
    ):
        return await self.repo.get_canonical_person_with_children(tenant_id, canonical_person_id)

    async def list_canonical_person_links(
        self,
        tenant_id: str,
        canonical_person_id: Optional[UUID] = None,
        person_entity_id: Optional[UUID] = None,
    ):
        return await self.repo.list_canonical_person_links(
            tenant_id=tenant_id,
            canonical_person_id=canonical_person_id,
            person_entity_id=person_entity_id,
        )

    # ========================================================================
    # Canonical Company Resolution (Stage 6.3)
    # ========================================================================

    async def run_canonical_company_resolution_step(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Resolve tenant-wide canonical companies with domain-first deterministic linking."""

        resolver = CanonicalCompanyService(self.db)
        summary = await resolver.resolve_run_companies(tenant_id=tenant_id, run_id=run_id)

        enriched_summary = {
            "stage": "6.3_canonical_companies",
            "entity_type": "company",
            **summary,
        }

        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="canonical_company_resolution",
                status="ok",
                input_json={"stage": "6.3_canonical_companies", "entity_type": "company"},
                output_json=enriched_summary,
            ),
        )

        return enriched_summary

    async def list_canonical_companies(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ):
        records = await self.repo.list_canonical_companies_with_counts(tenant_id, limit=limit, offset=offset)
        results = []
        for company, count in records:
            results.append({
                "company": company,
                "linked_entities_count": int(count or 0),
            })
        return results

    async def get_canonical_company_detail(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
    ):
        return await self.repo.get_canonical_company_detail(tenant_id, canonical_company_id)

    async def list_canonical_company_links(
        self,
        tenant_id: str,
        canonical_company_id: Optional[UUID] = None,
        company_entity_id: Optional[UUID] = None,
    ):
        return await self.repo.list_canonical_company_links(
            tenant_id=tenant_id,
            canonical_company_id=canonical_company_id,
            company_entity_id=company_entity_id,
        )

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

"""
Company Research repository - database operations.

Handles CRUD operations for company discovery and agentic sourcing.
"""

from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID
import uuid

from sqlalchemy import select, func, desc, asc, and_, or_, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    RobotsPolicyCache,
    ExecutiveProspect,
    ExecutiveProspectEvidence,
    ExecutiveMergeDecision,
    ResolvedEntity,
    EntityMergeLink,
    CanonicalPerson,
    CanonicalPersonEmail,
    CanonicalPersonLink,
    CanonicalCompany,
    CanonicalCompanyDomain,
    CanonicalCompanyLink,
)
from app.models.ai_enrichment_record import AIEnrichmentRecord
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
from app.utils.time import utc_now


class CompanyResearchRepository:
    """Repository for company research operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ========================================================================
    # Company Research Run Operations
    # ========================================================================
    
    async def create_company_research_run(
        self,
        tenant_id: str,
        data: CompanyResearchRunCreate,
        created_by_user_id: Optional[UUID] = None,
    ) -> CompanyResearchRun:
        """Create a new company research run."""
        run = CompanyResearchRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_by_user_id=created_by_user_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run
    
    async def get_company_research_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> Optional[CompanyResearchRun]:
        """Get a company research run by ID."""
        result = await self.db.execute(
            select(CompanyResearchRun).where(
                CompanyResearchRun.id == run_id,
                CompanyResearchRun.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_company_research_runs_for_role(
        self,
        tenant_id: str,
        role_mandate_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyResearchRun]:
        """List all research runs for a specific role/mandate."""
        result = await self.db.execute(
            select(CompanyResearchRun)
            .where(
                CompanyResearchRun.tenant_id == tenant_id,
                CompanyResearchRun.role_mandate_id == role_mandate_id,
            )
            .order_by(desc(CompanyResearchRun.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_company_research_runs(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyResearchRun]:
        query = select(CompanyResearchRun).where(CompanyResearchRun.tenant_id == tenant_id)
        if status:
            query = query.where(CompanyResearchRun.status == status)

        query = query.order_by(CompanyResearchRun.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_company_research_run(
        self,
        tenant_id: str,
        run_id: UUID,
        data: CompanyResearchRunUpdate,
    ) -> Optional[CompanyResearchRun]:
        """Update a company research run."""
        run = await self.get_company_research_run(tenant_id, run_id)
        if not run:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(run, field, value)
        
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def set_run_status(
        self,
        tenant_id: str,
        run_id: UUID,
        status: str,
        last_error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> Optional[CompanyResearchRun]:
        run = await self.get_company_research_run(tenant_id, run_id)
        if not run:
            return None

        run.status = status
        if last_error is not None:
            run.last_error = last_error
        if started_at is not None:
            run.started_at = started_at
        if finished_at is not None:
            run.finished_at = finished_at

        await self.db.flush()
        await self.db.refresh(run)
        return run
    
    # ========================================================================
    # Company Prospect Operations
    # ========================================================================
    
    async def create_company_prospect(
        self,
        tenant_id: str,
        data: CompanyProspectCreate,
    ) -> CompanyProspect:
        """Create a new company prospect."""
        prospect = CompanyProspect(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(prospect)
        await self.db.flush()
        await self.db.refresh(prospect)
        return prospect
    
    async def get_company_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
    ) -> Optional[CompanyProspect]:
        """Get a company prospect by ID."""
        result = await self.db.execute(
            select(CompanyProspect).where(
                CompanyProspect.id == prospect_id,
                CompanyProspect.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_company_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        status: Optional[str] = None,
        min_relevance_score: Optional[float] = None,
        review_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        discovered_by: Optional[str] = None,
        exec_search_enabled: Optional[bool] = None,
        order_by: str = "ai",  # "ai", "manual", "assets", "revenue"
        limit: int = 50,
        offset: int = 0,
    ) -> List[CompanyProspect]:
        """
        List company prospects for a research run with filtering and ordering.
        
        Args:
            tenant_id: Tenant ID
            run_id: Research run ID
            status: Optional status filter
            min_relevance_score: Minimum relevance score filter
            order_by: Ordering mode - "ai" (relevance), "manual" (priority), etc.
            limit: Maximum results
            offset: Results offset
        
        Returns:
            List of company prospects
        """
        query = select(CompanyProspect).where(
            CompanyProspect.tenant_id == tenant_id,
            CompanyProspect.company_research_run_id == run_id,
        )
        
        # Apply filters
        if status:
            query = query.where(CompanyProspect.status == status)
        
        if min_relevance_score is not None:
            query = query.where(CompanyProspect.relevance_score >= min_relevance_score)

        if review_status:
            query = query.where(CompanyProspect.review_status == review_status)

        if verification_status:
            query = query.where(CompanyProspect.verification_status == verification_status)

        if discovered_by:
            query = query.where(CompanyProspect.discovered_by == discovered_by)

        if exec_search_enabled is not None:
            query = query.where(CompanyProspect.exec_search_enabled == exec_search_enabled)
        
        # Apply ordering
        if order_by == "manual":
            # Manual priority: pinned first, then manual_priority ASC (1=highest), then relevance
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                asc(CompanyProspect.manual_priority).nulls_last(),
                desc(CompanyProspect.relevance_score),
            )
        elif order_by == "ai_rank":
            # AI Rank: pinned first, then ai_rank ASC (1=highest)
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                asc(CompanyProspect.ai_rank).nulls_last(),
                desc(CompanyProspect.relevance_score),
            )
        elif order_by.startswith("metric:"):
            # Dynamic metric sorting: pinned first, then by specified metric
            from app.models.company_research import CompanyMetric
            from sqlalchemy.orm import aliased
            from sqlalchemy import case, cast, Integer
            
            # Extract metric key from "metric:total_assets"
            metric_key = order_by.split(":", 1)[1]
            
            metric_alias = aliased(CompanyMetric)
            query = query.outerjoin(
                metric_alias,
                and_(
                    metric_alias.company_prospect_id == CompanyProspect.id,
                    metric_alias.metric_key == metric_key
                )
            ).order_by(
                desc(CompanyProspect.is_pinned),
                # Sort by appropriate value_* column based on value_type
                # number: use value_number (desc), bool: use value_bool (true first), text: alphabetical
                desc(case(
                    (metric_alias.value_type == 'number', metric_alias.value_number),
                    (metric_alias.value_type == 'bool', cast(metric_alias.value_bool, Integer)),
                    else_=None
                )).nulls_last(),
                desc(CompanyProspect.relevance_score),
            )
        else:  # "ai" or default
            # AI ranking: pinned first, then relevance score
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                desc(CompanyProspect.relevance_score),
                desc(CompanyProspect.evidence_score),
            )
        
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_all_company_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        status: Optional[str] = None,
        min_relevance_score: Optional[float] = None,
    ) -> List[CompanyProspect]:
        """Fetch all prospects for a run without pagination for deterministic ranking."""
        query = select(CompanyProspect).where(
            CompanyProspect.tenant_id == tenant_id,
            CompanyProspect.company_research_run_id == run_id,
        )

        if status:
            query = query.where(CompanyProspect.status == status)
        if min_relevance_score is not None:
            query = query.where(CompanyProspect.relevance_score >= min_relevance_score)

        query = query.order_by(CompanyProspect.created_at.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
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
        List prospects for a run with evidence and source documents using efficient joins.
        Avoids N+1 queries by loading all related data in a single query.
        """
        from app.models.company_research import CompanyProspectEvidence, ResearchSourceDocument
        from sqlalchemy.orm import selectinload
        
        query = select(CompanyProspect).where(
            CompanyProspect.tenant_id == tenant_id,
            CompanyProspect.company_research_run_id == run_id,
        ).options(
            # Eagerly load evidence and their source documents
            selectinload(CompanyProspect.evidence).selectinload(CompanyProspectEvidence.source_document)
        )
        
        # Apply filters
        if status:
            query = query.where(CompanyProspect.status == status)
        
        if min_relevance_score is not None:
            query = query.where(CompanyProspect.relevance_score >= min_relevance_score)

        if review_status:
            query = query.where(CompanyProspect.review_status == review_status)

        if verification_status:
            query = query.where(CompanyProspect.verification_status == verification_status)

        if discovered_by:
            query = query.where(CompanyProspect.discovered_by == discovered_by)

        if exec_search_enabled is not None:
            query = query.where(CompanyProspect.exec_search_enabled == exec_search_enabled)
        
        # Apply ordering (same logic as the regular method)
        if order_by == "manual":
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                asc(CompanyProspect.manual_priority).nulls_last(),
                desc(CompanyProspect.relevance_score),
            )
        elif order_by == "ai_rank":
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                asc(CompanyProspect.ai_rank).nulls_last(),
                desc(CompanyProspect.relevance_score),
            )
        else:  # "ai" or default
            query = query.order_by(
                desc(CompanyProspect.is_pinned),
                desc(CompanyProspect.relevance_score),
                desc(CompanyProspect.evidence_score),
            )
        
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def update_company_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
        data: CompanyProspectUpdate,
    ) -> Optional[CompanyProspect]:
        """Update a company prospect (system use)."""
        prospect = await self.get_company_prospect(tenant_id, prospect_id)
        if not prospect:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(prospect, field, value)
        
        await self.db.flush()
        await self.db.refresh(prospect)
        return prospect
    
    async def update_company_prospect_manual_fields(
        self,
        tenant_id: str,
        prospect_id: UUID,
        data: CompanyProspectUpdateManual,
    ) -> Optional[CompanyProspect]:
        """
        Update company prospect manual override fields only.
        
        This method ONLY updates manual_priority, manual_notes, is_pinned, and status.
        It will NEVER touch AI-generated scores.
        """
        prospect = await self.get_company_prospect(tenant_id, prospect_id)
        if not prospect:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        
        # Whitelist of allowed manual fields
        allowed_fields = {'manual_priority', 'manual_notes', 'is_pinned', 'status'}
        
        for field, value in update_data.items():
            if field in allowed_fields:
                setattr(prospect, field, value)
        
        await self.db.flush()
        await self.db.refresh(prospect)
        return prospect
    
    async def count_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> int:
        """Count total prospects for a research run."""
        result = await self.db.execute(
            select(func.count(CompanyProspect.id)).where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
            )
        )
        return result.scalar() or 0
    
    # ========================================================================
    # Company Prospect Evidence Operations
    # ========================================================================
    
    async def create_company_prospect_evidence(
        self,
        tenant_id: str,
        data: CompanyProspectEvidenceCreate,
    ) -> CompanyProspectEvidence:
        """Create a new evidence record for a company prospect."""
        evidence = CompanyProspectEvidence(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(evidence)
        await self.db.flush()
        await self.db.refresh(evidence)
        return evidence
    
    async def list_evidence_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
    ) -> List[CompanyProspectEvidence]:
        """List all evidence records for a specific company prospect."""
        result = await self.db.execute(
            select(CompanyProspectEvidence)
            .where(
                CompanyProspectEvidence.tenant_id == tenant_id,
                CompanyProspectEvidence.company_prospect_id == prospect_id,
            )
            .order_by(desc(CompanyProspectEvidence.evidence_weight), desc(CompanyProspectEvidence.created_at))
        )
        return list(result.scalars().all())

    async def list_company_prospects_with_website(
        self,
        tenant_id: str,
    ) -> List[CompanyProspect]:
        result = await self.db.execute(
            select(CompanyProspect)
            .where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.website_url.is_not(None),
            )
            .order_by(CompanyProspect.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_company_prospects_for_run_with_website(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[CompanyProspect]:
        result = await self.db.execute(
            select(CompanyProspect)
            .where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.company_research_run_id == run_id,
                CompanyProspect.website_url.is_not(None),
            )
            .order_by(CompanyProspect.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_company_prospects_with_country(
        self,
        tenant_id: str,
    ) -> List[CompanyProspect]:
        result = await self.db.execute(
            select(CompanyProspect)
            .where(
                CompanyProspect.tenant_id == tenant_id,
                CompanyProspect.hq_country.is_not(None),
            )
            .order_by(CompanyProspect.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_company_evidence_for_prospect_ids(
        self,
        tenant_id: str,
        prospect_ids: List[UUID],
    ) -> List[CompanyProspectEvidence]:
        if not prospect_ids:
            return []

        result = await self.db.execute(
            select(CompanyProspectEvidence)
            .where(
                CompanyProspectEvidence.tenant_id == tenant_id,
                CompanyProspectEvidence.company_prospect_id.in_(prospect_ids),
            )
            .order_by(CompanyProspectEvidence.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_executive_prospects_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ExecutiveProspect]:
        result = await self.db.execute(
            select(ExecutiveProspect)
            .where(
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.company_research_run_id == run_id,
            )
            .order_by(ExecutiveProspect.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_executive_prospect(
        self,
        tenant_id: str,
        executive_id: UUID,
    ) -> Optional[ExecutiveProspect]:
        result = await self.db.execute(
            select(ExecutiveProspect)
            .options(
                selectinload(ExecutiveProspect.evidence),
                selectinload(ExecutiveProspect.company_prospect),
            )
            .where(
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.id == executive_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_executive_evidence_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ExecutiveProspectEvidence]:
        result = await self.db.execute(
            select(ExecutiveProspectEvidence)
            .join(ExecutiveProspect, ExecutiveProspect.id == ExecutiveProspectEvidence.executive_prospect_id)
            .where(
                ExecutiveProspectEvidence.tenant_id == tenant_id,
                ExecutiveProspect.tenant_id == tenant_id,
                ExecutiveProspect.company_research_run_id == run_id,
            )
            .order_by(ExecutiveProspectEvidence.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_executive_prospects_by_email(
        self,
        tenant_id: str,
        email_normalized: str,
    ) -> List[ExecutiveProspect]:
        query = (
            select(ExecutiveProspect)
            .where(
                ExecutiveProspect.tenant_id == tenant_id,
                func.lower(ExecutiveProspect.email) == email_normalized,
            )
            .order_by(ExecutiveProspect.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_executive_prospects_by_linkedin(
        self,
        tenant_id: str,
        linkedin_normalized: str,
    ) -> List[ExecutiveProspect]:
        query = (
            select(ExecutiveProspect)
            .where(
                ExecutiveProspect.tenant_id == tenant_id,
                func.lower(ExecutiveProspect.linkedin_url) == linkedin_normalized,
            )
            .order_by(ExecutiveProspect.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_executive_evidence_for_exec_ids(
        self,
        tenant_id: str,
        exec_ids: List[UUID],
    ) -> List[ExecutiveProspectEvidence]:
        if not exec_ids:
            return []
        query = (
            select(ExecutiveProspectEvidence)
            .where(
                ExecutiveProspectEvidence.tenant_id == tenant_id,
                ExecutiveProspectEvidence.executive_prospect_id.in_(exec_ids),
            )
            .order_by(ExecutiveProspectEvidence.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_merge_decision(
        self,
        tenant_id: str,
        run_id: UUID,
        left_executive_id: UUID,
        right_executive_id: UUID,
    ) -> Optional[ExecutiveMergeDecision]:
        left_id, right_id = sorted([left_executive_id, right_executive_id], key=str)
        result = await self.db.execute(
            select(ExecutiveMergeDecision).where(
                ExecutiveMergeDecision.tenant_id == tenant_id,
                ExecutiveMergeDecision.company_research_run_id == run_id,
                ExecutiveMergeDecision.left_executive_id == left_id,
                ExecutiveMergeDecision.right_executive_id == right_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_merge_decision(
        self,
        tenant_id: str,
        run_id: UUID,
        *,
        company_prospect_id: Optional[UUID],
        canonical_company_id: Optional[UUID],
        left_executive_id: UUID,
        right_executive_id: UUID,
        decision_type: str,
        note: Optional[str],
        evidence_source_document_ids: list[UUID] | None,
        evidence_enrichment_ids: list[UUID] | None,
        created_by: Optional[str],
    ) -> tuple[ExecutiveMergeDecision, bool]:
        left_id, right_id = sorted([left_executive_id, right_executive_id], key=str)
        evidence_docs = sorted({str(eid) for eid in evidence_source_document_ids or []})
        evidence_enrich = sorted({str(eid) for eid in evidence_enrichment_ids or []})

        existing = await self.get_merge_decision(tenant_id, run_id, left_id, right_id)
        if existing:
            if existing.decision_type != decision_type:
                raise ValueError("decision_conflict")

            merged_docs = sorted({*(existing.evidence_source_document_ids or []), *evidence_docs}, key=str)
            merged_enrich = sorted({*(existing.evidence_enrichment_ids or []), *evidence_enrich}, key=str)
            existing.evidence_source_document_ids = merged_docs
            existing.evidence_enrichment_ids = merged_enrich
            if note:
                existing.note = note
            if created_by:
                existing.created_by = created_by
            await self.db.flush()
            await self.db.refresh(existing)
            return existing, False

        payload = {
            "tenant_id": tenant_id,
            "company_research_run_id": run_id,
            "company_prospect_id": company_prospect_id,
            "canonical_company_id": canonical_company_id,
            "left_executive_id": left_id,
            "right_executive_id": right_id,
            "decision_type": decision_type,
            "note": note,
            "evidence_source_document_ids": evidence_docs,
            "evidence_enrichment_ids": evidence_enrich,
            "created_by": created_by,
        }

        stmt = (
            insert(ExecutiveMergeDecision)
            .values(**payload)
            .on_conflict_do_nothing(index_elements=[
                ExecutiveMergeDecision.tenant_id,
                ExecutiveMergeDecision.company_research_run_id,
                ExecutiveMergeDecision.left_executive_id,
                ExecutiveMergeDecision.right_executive_id,
            ])
            .returning(ExecutiveMergeDecision)
        )
        result = await self.db.execute(stmt)
        created = result.scalar_one_or_none()
        if created:
            await self.db.flush()
            await self.db.refresh(created)
            return created, True

        existing = await self.get_merge_decision(tenant_id, run_id, left_id, right_id)
        if existing:
            return existing, False
        raise RuntimeError("merge_decision_upsert_failed")

    async def list_merge_decisions_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        canonical_company_id: Optional[UUID] = None,
    ) -> List[ExecutiveMergeDecision]:
        query = select(ExecutiveMergeDecision).where(
            ExecutiveMergeDecision.tenant_id == tenant_id,
            ExecutiveMergeDecision.company_research_run_id == run_id,
        )
        if canonical_company_id:
            query = query.where(ExecutiveMergeDecision.canonical_company_id == canonical_company_id)

        result = await self.db.execute(query.order_by(ExecutiveMergeDecision.created_at.asc()))
        return list(result.scalars().all())

    async def list_source_documents_by_ids(
        self,
        tenant_id: str,
        source_ids: List[UUID],
    ) -> List[ResearchSourceDocument]:
        ids = list({sid for sid in source_ids if sid})
        if not ids:
            return []
        result = await self.db.execute(
            select(ResearchSourceDocument).where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.id.in_(ids),
            )
        )
        return list(result.scalars().all())

    async def list_enrichment_records_for_sources(
        self,
        tenant_id: str,
        source_ids: List[UUID],
    ) -> List[AIEnrichmentRecord]:
        ids = list({sid for sid in source_ids if sid})
        if not ids:
            return []
        result = await self.db.execute(
            select(AIEnrichmentRecord).where(
                AIEnrichmentRecord.tenant_id == tenant_id,
                AIEnrichmentRecord.source_document_id.in_(ids),
            )
        )
        return list(result.scalars().all())
    
    # ========================================================================
    # Company Prospect Metric Operations
    # ========================================================================
    
    async def create_company_prospect_metric(
        self,
        tenant_id: str,
        data: CompanyProspectMetricCreate,
    ) -> CompanyProspectMetric:
        """Create a new metric record for a company prospect."""
        metric = CompanyProspectMetric(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(metric)
        await self.db.flush()
        await self.db.refresh(metric)
        return metric
    
    async def list_metrics_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
        metric_type: Optional[str] = None,
    ) -> List[CompanyProspectMetric]:
        """List all metrics for a specific company prospect."""
        query = select(CompanyProspectMetric).where(
            CompanyProspectMetric.tenant_id == tenant_id,
            CompanyProspectMetric.company_prospect_id == prospect_id,
        )
        
        if metric_type:
            query = query.where(CompanyProspectMetric.metric_type == metric_type)
        
        query = query.order_by(
            CompanyProspectMetric.metric_type,
            desc(CompanyProspectMetric.as_of_year).nulls_last(),
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_latest_metric_for_prospect(
        self,
        tenant_id: str,
        prospect_id: UUID,
        metric_type: str,
    ) -> Optional[CompanyProspectMetric]:
        """Get the most recent metric of a specific type for a prospect."""
        result = await self.db.execute(
            select(CompanyProspectMetric)
            .where(
                CompanyProspectMetric.tenant_id == tenant_id,
                CompanyProspectMetric.company_prospect_id == prospect_id,
                CompanyProspectMetric.metric_type == metric_type,
            )
            .order_by(desc(CompanyProspectMetric.as_of_year).nulls_last(), desc(CompanyProspectMetric.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    # ========================================================================
    # Source Document Operations
    # ========================================================================
    
    async def create_source_document(
        self,
        tenant_id: str,
        data: SourceDocumentCreate,
    ) -> ResearchSourceDocument:
        """Create a new source document."""
        source = ResearchSourceDocument(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            status="queued" if data.source_type == "url" else "new",
            attempt_count=0,
            max_attempts=data.max_attempts or 3,
            next_retry_at=None,
            last_error=None,
            original_url=data.original_url or data.url,
            **data.model_dump(exclude={"max_attempts", "original_url"}),
        )
        self.db.add(source)
        await self.db.flush()  # Flush to get DB defaults
        await self.db.refresh(source)
        return source
    
    async def get_source_document(
        self,
        tenant_id: str,
        source_id: UUID,
    ) -> Optional[ResearchSourceDocument]:
        """Get a source document by ID."""
        result = await self.db.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.id == source_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def list_source_documents_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ResearchSourceDocument]:
        """List all source documents for a research run."""
        result = await self.db.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.company_research_run_id == run_id,
            )
            .order_by(ResearchSourceDocument.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_source_by_hash(
        self,
        tenant_id: str,
        run_id: UUID,
        content_hash: str,
        exclude_id: Optional[UUID] = None,
    ) -> Optional[ResearchSourceDocument]:
        """Find earliest source in a run with the same content hash."""
        query = (
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.company_research_run_id == run_id,
                ResearchSourceDocument.content_hash == content_hash,
            )
            .order_by(ResearchSourceDocument.created_at.asc())
            .limit(1)
        )
        if exclude_id:
            query = query.where(ResearchSourceDocument.id != exclude_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_source_document(
        self,
        tenant_id: str,
        source_id: UUID,
        data: SourceDocumentUpdate,
    ) -> Optional[ResearchSourceDocument]:
        """Update a source document."""
        source = await self.get_source_document(tenant_id, source_id)
        if not source:
            return None
        
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(source, field, value)
        
        await self.db.commit()
        await self.db.refresh(source)
        return source
    
    async def get_extractable_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ResearchSourceDocument]:
        """Get sources ready for extraction.

        URL sources must already be fetched; non-URL sources can be new or fetched.
        """
        result = await self.db.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.company_research_run_id == run_id,
                or_(
                    and_(
                        ResearchSourceDocument.source_type == 'url',
                        ResearchSourceDocument.status == 'fetched',
                    ),
                    and_(
                        ResearchSourceDocument.source_type != 'url',
                        ResearchSourceDocument.status.in_(['new', 'fetched']),
                    ),
                ),
            )
            .order_by(ResearchSourceDocument.created_at)
        )
        return list(result.scalars().all())

    async def get_url_sources_to_fetch(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ResearchSourceDocument]:
        """Return URL sources needing fetch attempts.

        Includes fetched sources that explicitly request a conditional recheck via
        meta.validators.pending_recheck, while preserving the original queue
        semantics for queued/failed sources.
        """

        result = await self.db.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.company_research_run_id == run_id,
                ResearchSourceDocument.source_type == 'url',
                ResearchSourceDocument.status.in_(['queued', 'fetch_failed', 'failed', 'fetched']),
                or_(
                    ResearchSourceDocument.next_retry_at.is_(None),
                    ResearchSourceDocument.next_retry_at <= func.now(),
                ),
            )
            .order_by(ResearchSourceDocument.created_at)
        )

        sources = list(result.scalars().all())
        filtered: list[ResearchSourceDocument] = []
        for source in sources:
            if source.status != 'fetched':
                if (source.attempt_count or 0) >= (source.max_attempts or 0):
                    continue
                filtered.append(source)
                continue

            meta = source.meta or {}
            validators = (meta.get("validators") or {}) if isinstance(meta, dict) else {}
            if validators.get("pending_recheck"):
                filtered.append(source)

        return filtered

    # ========================================================================
    # Robots Policy Cache Operations
    # ========================================================================

    async def get_cached_robots_policy(
        self,
        tenant_id: str,
        domain: str,
        user_agent: str,
    ) -> Optional[RobotsPolicyCache]:
        domain_norm = (domain or "").lower()
        user_agent_norm = (user_agent or "").lower()
        result = await self.db.execute(
            select(RobotsPolicyCache).where(
                RobotsPolicyCache.tenant_id == tenant_id,
                RobotsPolicyCache.domain == domain_norm,
                RobotsPolicyCache.user_agent == user_agent_norm,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_robots_policy_cache(
        self,
        tenant_id: str,
        domain: str,
        user_agent: str,
        policy: dict,
        origin: Optional[str],
        status_code: Optional[int],
        fetched_at: datetime,
        expires_at: datetime,
    ) -> RobotsPolicyCache:
        domain_norm = (domain or "").lower()
        user_agent_norm = (user_agent or "").lower()

        insert_stmt = insert(RobotsPolicyCache).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            domain=domain_norm,
            user_agent=user_agent_norm,
            policy=policy,
            origin=origin,
            status_code=status_code,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )

        upsert_stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_robots_policy_cache",
            set_={
                "policy": insert_stmt.excluded.policy,
                "origin": insert_stmt.excluded.origin,
                "status_code": insert_stmt.excluded.status_code,
                "fetched_at": insert_stmt.excluded.fetched_at,
                "expires_at": insert_stmt.excluded.expires_at,
                "updated_at": func.now(),
            },
        ).returning(RobotsPolicyCache)

        result = await self.db.execute(upsert_stmt)
        await self.db.flush()
        return result.scalar_one()
    
    # ========================================================================
    # Research Event Operations
    # ========================================================================
    
    async def create_research_event(
        self,
        tenant_id: str,
        data: ResearchEventCreate,
    ) -> CompanyResearchEvent:
        """Create a new research event (audit log)."""
        event = CompanyResearchEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'}),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event
    
    async def list_research_events_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        limit: int = 100,
    ) -> List[CompanyResearchEvent]:
        """List research events for a run (most recent first)."""
        result = await self.db.execute(
            select(CompanyResearchEvent)
            .where(
                CompanyResearchEvent.tenant_id == tenant_id,
                CompanyResearchEvent.company_research_run_id == run_id,
            )
            .order_by(CompanyResearchEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ========================================================================
    # Entity Resolution Operations
    # ========================================================================

    async def upsert_resolved_entity(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: str,
        canonical_entity_id: UUID,
        match_keys: dict,
        reason_codes: list,
        evidence_source_document_ids: list,
        resolution_hash: str,
    ) -> ResolvedEntity:
        base_insert = insert(ResolvedEntity).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            company_research_run_id=run_id,
            entity_type=entity_type,
            canonical_entity_id=canonical_entity_id,
            match_keys=match_keys,
            reason_codes=reason_codes,
            evidence_source_document_ids=evidence_source_document_ids,
            resolution_hash=resolution_hash,
        )

        insert_stmt = base_insert.on_conflict_do_update(
            constraint="uq_resolved_entities_hash",
            set_={
                "match_keys": base_insert.excluded.match_keys,
                "reason_codes": base_insert.excluded.reason_codes,
                "evidence_source_document_ids": base_insert.excluded.evidence_source_document_ids,
                "updated_at": func.now(),
            },
        ).returning(ResolvedEntity)
        result = await self.db.execute(insert_stmt)
        resolved = result.scalar_one()
        await self.db.flush()
        return resolved

    async def upsert_entity_merge_link(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: str,
        resolved_entity_id: UUID,
        canonical_entity_id: UUID,
        duplicate_entity_id: UUID,
        match_keys: dict,
        reason_codes: list,
        evidence_source_document_ids: list,
        resolution_hash: str,
    ) -> EntityMergeLink:
        base_insert = insert(EntityMergeLink).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            company_research_run_id=run_id,
            entity_type=entity_type,
            resolved_entity_id=resolved_entity_id,
            canonical_entity_id=canonical_entity_id,
            duplicate_entity_id=duplicate_entity_id,
            match_keys=match_keys,
            reason_codes=reason_codes,
            evidence_source_document_ids=evidence_source_document_ids,
            resolution_hash=resolution_hash,
        )

        insert_stmt = base_insert.on_conflict_do_update(
            constraint="uq_entity_merge_links_hash",
            set_={
                "match_keys": base_insert.excluded.match_keys,
                "reason_codes": base_insert.excluded.reason_codes,
                "evidence_source_document_ids": base_insert.excluded.evidence_source_document_ids,
                "resolved_entity_id": base_insert.excluded.resolved_entity_id,
                "updated_at": func.now(),
            },
        ).returning(EntityMergeLink)
        result = await self.db.execute(insert_stmt)
        link = result.scalar_one()
        await self.db.flush()
        return link

    async def list_resolved_entities_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: Optional[str] = None,
    ) -> List[ResolvedEntity]:
        query = select(ResolvedEntity).where(
            ResolvedEntity.tenant_id == tenant_id,
            ResolvedEntity.company_research_run_id == run_id,
        )
        if entity_type:
            query = query.where(ResolvedEntity.entity_type == entity_type)
        query = query.order_by(
            ResolvedEntity.canonical_entity_id.asc(),
            ResolvedEntity.resolution_hash.asc(),
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_entity_merge_links_for_run(
        self,
        tenant_id: str,
        run_id: UUID,
        entity_type: Optional[str] = None,
    ) -> List[EntityMergeLink]:
        query = select(EntityMergeLink).where(
            EntityMergeLink.tenant_id == tenant_id,
            EntityMergeLink.company_research_run_id == run_id,
        )
        if entity_type:
            query = query.where(EntityMergeLink.entity_type == entity_type)
        query = query.order_by(
            EntityMergeLink.canonical_entity_id.asc(),
            EntityMergeLink.duplicate_entity_id.asc(),
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ====================================================================
    # Canonical Companies Operations (Stage 6.3)
    # ====================================================================

    async def get_canonical_company_by_domain(
        self,
        tenant_id: str,
        domain_normalized: str,
    ) -> Optional[CanonicalCompany]:
        query = (
            select(CanonicalCompany)
            .join(CanonicalCompanyDomain, CanonicalCompanyDomain.canonical_company_id == CanonicalCompany.id)
            .options(
                selectinload(CanonicalCompany.domains),
                selectinload(CanonicalCompany.links),
            )
            .where(
                CanonicalCompanyDomain.tenant_id == tenant_id,
                CanonicalCompanyDomain.domain_normalized == domain_normalized,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_canonical_company_by_name_country(
        self,
        tenant_id: str,
        name_normalized: str,
        country_code: str,
    ) -> Optional[CanonicalCompany]:
        query = (
            select(CanonicalCompany)
            .options(
                selectinload(CanonicalCompany.domains),
                selectinload(CanonicalCompany.links),
            )
            .where(
                CanonicalCompany.tenant_id == tenant_id,
                func.lower(CanonicalCompany.canonical_name) == func.lower(name_normalized),
                CanonicalCompany.country_code == country_code,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_canonical_company(
        self,
        tenant_id: str,
        canonical_name: Optional[str] = None,
        primary_domain: Optional[str] = None,
        country_code: Optional[str] = None,
    ) -> CanonicalCompany:
        company = CanonicalCompany(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_name=canonical_name,
            primary_domain=primary_domain,
            country_code=country_code,
        )
        self.db.add(company)
        await self.db.flush()
        await self.db.refresh(company)
        return company

    async def upsert_canonical_company_domain(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
        domain_normalized: str,
    ) -> CanonicalCompanyDomain:
        base_insert = insert(CanonicalCompanyDomain).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_company_id=canonical_company_id,
            domain_normalized=domain_normalized,
        )
        stmt = base_insert.on_conflict_do_update(
            constraint="uq_canonical_company_domains_domain",
            set_={
                "canonical_company_id": base_insert.excluded.canonical_company_id,
                "updated_at": func.now(),
            },
        ).returning(CanonicalCompanyDomain)
        result = await self.db.execute(stmt)
        record = result.scalar_one()
        await self.db.flush()
        return record

    async def upsert_canonical_company_link(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
        company_entity_id: UUID,
        match_rule: str,
        evidence_source_document_id: UUID,
        evidence_company_research_run_id: Optional[UUID],
    ) -> CanonicalCompanyLink:
        base_insert = insert(CanonicalCompanyLink).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_company_id=canonical_company_id,
            company_entity_id=company_entity_id,
            match_rule=match_rule,
            evidence_source_document_id=evidence_source_document_id,
            evidence_company_research_run_id=evidence_company_research_run_id,
        )
        stmt = base_insert.on_conflict_do_update(
            constraint="uq_canonical_company_links_entity",
            set_={
                "canonical_company_id": base_insert.excluded.canonical_company_id,
                "match_rule": base_insert.excluded.match_rule,
                "evidence_source_document_id": base_insert.excluded.evidence_source_document_id,
                "evidence_company_research_run_id": base_insert.excluded.evidence_company_research_run_id,
                "updated_at": func.now(),
            },
        ).returning(CanonicalCompanyLink)
        result = await self.db.execute(stmt)
        link = result.scalar_one()
        await self.db.flush()
        return link

    async def list_canonical_companies_with_counts(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[tuple[CanonicalCompany, int]]:
        link_count = func.count(CanonicalCompanyLink.id)
        query = (
            select(CanonicalCompany, link_count)
            .outerjoin(CanonicalCompanyLink, and_(
                CanonicalCompanyLink.tenant_id == CanonicalCompany.tenant_id,
                CanonicalCompanyLink.canonical_company_id == CanonicalCompany.id,
            ))
            .where(CanonicalCompany.tenant_id == tenant_id)
            .group_by(CanonicalCompany.id)
            .order_by(CanonicalCompany.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        return list(result.all())

    async def get_canonical_company_detail(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
    ) -> Optional[CanonicalCompany]:
        query = (
            select(CanonicalCompany)
            .options(
                selectinload(CanonicalCompany.domains),
                selectinload(CanonicalCompany.links),
            )
            .where(
                CanonicalCompany.tenant_id == tenant_id,
                CanonicalCompany.id == canonical_company_id,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_canonical_company_links(
        self,
        tenant_id: str,
        canonical_company_id: Optional[UUID] = None,
        company_entity_id: Optional[UUID] = None,
    ) -> List[CanonicalCompanyLink]:
        query = select(CanonicalCompanyLink).where(CanonicalCompanyLink.tenant_id == tenant_id)
        if canonical_company_id:
            query = query.where(CanonicalCompanyLink.canonical_company_id == canonical_company_id)
        if company_entity_id:
            query = query.where(CanonicalCompanyLink.company_entity_id == company_entity_id)
        query = query.order_by(CanonicalCompanyLink.created_at.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_canonical_links_for_prospects(
        self,
        tenant_id: str,
        prospect_ids: List[UUID],
        run_id: Optional[UUID] = None,
    ) -> List[CanonicalCompanyLink]:
        """Fetch canonical company links for a batch of prospect IDs."""
        if not prospect_ids:
            return []

        query = select(CanonicalCompanyLink).where(
            CanonicalCompanyLink.tenant_id == tenant_id,
            CanonicalCompanyLink.company_entity_id.in_(prospect_ids),
        )

        if run_id:
            query = query.where(
                or_(
                    CanonicalCompanyLink.evidence_company_research_run_id == run_id,
                    CanonicalCompanyLink.evidence_company_research_run_id.is_(None),
                )
            )

        query = query.order_by(
            CanonicalCompanyLink.company_entity_id.asc(),
            CanonicalCompanyLink.created_at.asc(),
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ====================================================================
    # Canonical People Operations (Stage 6.2)
    # ====================================================================

    async def get_canonical_person_by_email(
        self,
        tenant_id: str,
        email_normalized: str,
    ) -> Optional[CanonicalPerson]:
        query = (
            select(CanonicalPerson)
            .join(CanonicalPersonEmail, CanonicalPersonEmail.canonical_person_id == CanonicalPerson.id)
            .options(selectinload(CanonicalPerson.emails), selectinload(CanonicalPerson.links))
            .where(
                CanonicalPersonEmail.tenant_id == tenant_id,
                CanonicalPersonEmail.email_normalized == email_normalized,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_canonical_person_by_linkedin(
        self,
        tenant_id: str,
        linkedin_normalized: str,
    ) -> Optional[CanonicalPerson]:
        query = (
            select(CanonicalPerson)
            .options(selectinload(CanonicalPerson.emails), selectinload(CanonicalPerson.links))
            .where(
                CanonicalPerson.tenant_id == tenant_id,
                func.lower(CanonicalPerson.primary_linkedin_url) == linkedin_normalized,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_canonical_person(
        self,
        tenant_id: str,
        canonical_full_name: Optional[str] = None,
        primary_email: Optional[str] = None,
        primary_linkedin_url: Optional[str] = None,
    ) -> CanonicalPerson:
        person = CanonicalPerson(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_full_name=canonical_full_name,
            primary_email=primary_email,
            primary_linkedin_url=primary_linkedin_url,
        )
        self.db.add(person)
        await self.db.flush()
        await self.db.refresh(person)
        return person

    async def upsert_canonical_person_email(
        self,
        tenant_id: str,
        canonical_person_id: UUID,
        email_normalized: str,
    ) -> CanonicalPersonEmail:
        base_insert = insert(CanonicalPersonEmail).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_person_id=canonical_person_id,
            email_normalized=email_normalized,
        )
        stmt = base_insert.on_conflict_do_update(
            constraint="uq_canonical_person_emails_unique_email",
            set_={
                "canonical_person_id": base_insert.excluded.canonical_person_id,
                "updated_at": func.now(),
            },
        ).returning(CanonicalPersonEmail)
        result = await self.db.execute(stmt)
        email = result.scalar_one()
        await self.db.flush()
        return email

    async def upsert_canonical_person_link(
        self,
        tenant_id: str,
        canonical_person_id: UUID,
        person_entity_id: UUID,
        match_rule: str,
        evidence_source_document_id: UUID,
        evidence_company_research_run_id: Optional[UUID],
    ) -> CanonicalPersonLink:
        base_insert = insert(CanonicalPersonLink).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            canonical_person_id=canonical_person_id,
            person_entity_id=person_entity_id,
            match_rule=match_rule,
            evidence_source_document_id=evidence_source_document_id,
            evidence_company_research_run_id=evidence_company_research_run_id,
        )
        stmt = base_insert.on_conflict_do_update(
            constraint="uq_canonical_person_links_person",
            set_={
                "canonical_person_id": base_insert.excluded.canonical_person_id,
                "match_rule": base_insert.excluded.match_rule,
                "evidence_source_document_id": base_insert.excluded.evidence_source_document_id,
                "evidence_company_research_run_id": base_insert.excluded.evidence_company_research_run_id,
                "updated_at": func.now(),
            },
        ).returning(CanonicalPersonLink)
        result = await self.db.execute(stmt)
        link = result.scalar_one()
        await self.db.flush()
        return link

    async def list_canonical_people_with_counts(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[tuple[CanonicalPerson, int]]:
        link_count = func.count(CanonicalPersonLink.id)
        query = (
            select(CanonicalPerson, link_count)
            .outerjoin(CanonicalPersonLink, and_(
                CanonicalPersonLink.tenant_id == CanonicalPerson.tenant_id,
                CanonicalPersonLink.canonical_person_id == CanonicalPerson.id,
            ))
            .where(CanonicalPerson.tenant_id == tenant_id)
            .group_by(CanonicalPerson.id)
            .order_by(CanonicalPerson.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        return list(result.all())

    async def get_canonical_person_with_children(
        self,
        tenant_id: str,
        canonical_person_id: UUID,
    ) -> Optional[CanonicalPerson]:
        query = (
            select(CanonicalPerson)
            .options(
                selectinload(CanonicalPerson.emails),
                selectinload(CanonicalPerson.links),
            )
            .where(
                CanonicalPerson.tenant_id == tenant_id,
                CanonicalPerson.id == canonical_person_id,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_canonical_person_links(
        self,
        tenant_id: str,
        canonical_person_id: Optional[UUID] = None,
        person_entity_id: Optional[UUID] = None,
    ) -> List[CanonicalPersonLink]:
        query = select(CanonicalPersonLink).where(CanonicalPersonLink.tenant_id == tenant_id)
        if canonical_person_id:
            query = query.where(CanonicalPersonLink.canonical_person_id == canonical_person_id)
        if person_entity_id:
            query = query.where(CanonicalPersonLink.person_entity_id == person_entity_id)
        query = query.order_by(CanonicalPersonLink.created_at.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ====================================================================
    # Job Queue Operations
    # ====================================================================

    async def enqueue_run_job(
        self,
        tenant_id: str,
        run_id: UUID,
        job_type: str = "company_research_run",
        max_attempts: int = 10,
    ) -> CompanyResearchJob:
        stmt = (
            insert(CompanyResearchJob)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                run_id=run_id,
                job_type=job_type,
                status="queued",
                max_attempts=max_attempts,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CompanyResearchJob.tenant_id,
                    CompanyResearchJob.run_id,
                    CompanyResearchJob.job_type,
                ],
                index_where=text("status IN ('queued','running')"),
            )
            .returning(CompanyResearchJob)
        )

        result = await self.db.execute(stmt)
        job = result.scalar_one_or_none()
        if job:
            return job

        # Return existing active job if conflict occurred
        result = await self.db.execute(
            select(CompanyResearchJob).where(
                CompanyResearchJob.tenant_id == tenant_id,
                CompanyResearchJob.run_id == run_id,
                CompanyResearchJob.job_type == job_type,
                CompanyResearchJob.status.in_(["queued", "running"]),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        # Fallback: fetch latest job
        result = await self.db.execute(
            select(CompanyResearchJob)
            .where(
                CompanyResearchJob.tenant_id == tenant_id,
                CompanyResearchJob.run_id == run_id,
            )
            .order_by(CompanyResearchJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one()

    # ====================================================================
    # Plan and Steps Operations
    # ====================================================================

    async def get_run_plan(self, tenant_id: str, run_id: UUID) -> Optional[CompanyResearchRunPlan]:
        result = await self.db.execute(
            select(CompanyResearchRunPlan).where(
                CompanyResearchRunPlan.tenant_id == tenant_id,
                CompanyResearchRunPlan.run_id == run_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_plan_if_missing(
        self,
        tenant_id: str,
        run_id: UUID,
        plan_json: dict,
        version: int = 1,
    ) -> CompanyResearchRunPlan:
        stmt = (
            insert(CompanyResearchRunPlan)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                run_id=run_id,
                version=version,
                plan_json=plan_json,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CompanyResearchRunPlan.tenant_id,
                    CompanyResearchRunPlan.run_id,
                ]
            )
            .returning(CompanyResearchRunPlan)
        )
        result = await self.db.execute(stmt)
        plan = result.scalar_one_or_none()
        if plan:
            return plan

        # fetch existing
        return await self.get_run_plan(tenant_id, run_id)

    async def lock_plan(self, tenant_id: str, run_id: UUID) -> Optional[CompanyResearchRunPlan]:
        plan = await self.get_run_plan(tenant_id, run_id)
        if not plan:
            return None
        if not plan.locked_at:
            plan.locked_at = utc_now()
            await self.db.flush()
            await self.db.refresh(plan)
        return plan

    async def list_steps(self, tenant_id: str, run_id: UUID) -> List[CompanyResearchRunStep]:
        result = await self.db.execute(
            select(CompanyResearchRunStep)
            .where(
                CompanyResearchRunStep.tenant_id == tenant_id,
                CompanyResearchRunStep.run_id == run_id,
            )
            .order_by(CompanyResearchRunStep.step_order)
        )
        return list(result.scalars().all())

    async def upsert_steps(self, tenant_id: str, run_id: UUID, steps: List[dict]) -> List[CompanyResearchRunStep]:
        created_steps: List[CompanyResearchRunStep] = []
        for step in steps:
            stmt = (
                insert(CompanyResearchRunStep)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    run_id=run_id,
                    step_key=step["step_key"],
                    step_order=step["step_order"],
                    status=step.get("status", "pending"),
                    max_attempts=step.get("max_attempts", 2),
                    input_json=step.get("input_json"),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        CompanyResearchRunStep.tenant_id,
                        CompanyResearchRunStep.run_id,
                        CompanyResearchRunStep.step_key,
                    ]
                )
                .returning(CompanyResearchRunStep)
            )
            result = await self.db.execute(stmt)
            inserted = result.scalar_one_or_none()
            if inserted:
                created_steps.append(inserted)
        # Return current list
        return await self.list_steps(tenant_id, run_id)

    async def claim_next_step(self, tenant_id: str, run_id: UUID) -> Optional[CompanyResearchRunStep]:
        now = func.now()
        result = await self.db.execute(
            select(CompanyResearchRunStep)
            .where(
                CompanyResearchRunStep.tenant_id == tenant_id,
                CompanyResearchRunStep.run_id == run_id,
                CompanyResearchRunStep.status.in_(["pending", "failed"]),
                CompanyResearchRunStep.attempt_count < CompanyResearchRunStep.max_attempts,
                or_(
                    CompanyResearchRunStep.next_retry_at.is_(None),
                    CompanyResearchRunStep.next_retry_at <= now,
                ),
            )
            .order_by(CompanyResearchRunStep.step_order)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        step = result.scalar_one_or_none()
        if not step:
            return None
        step.status = "running"
        step.attempt_count = step.attempt_count + 1
        if not step.started_at:
            step.started_at = utc_now()
        step.next_retry_at = None
        await self.db.flush()
        await self.db.refresh(step)
        return step

    async def mark_step_succeeded(
        self,
        step_id: UUID,
        output_json: Optional[dict] = None,
    ) -> Optional[CompanyResearchRunStep]:
        result = await self.db.execute(
            select(CompanyResearchRunStep).where(CompanyResearchRunStep.id == step_id).with_for_update()
        )
        step = result.scalar_one_or_none()
        if not step:
            return None
        step.status = "succeeded"
        step.finished_at = utc_now()
        if output_json is not None:
            step.output_json = output_json
        await self.db.flush()
        await self.db.refresh(step)
        return step

    async def mark_step_failed(
        self,
        step_id: UUID,
        last_error: str,
        backoff_seconds: int = 30,
    ) -> Optional[CompanyResearchRunStep]:
        result = await self.db.execute(
            select(CompanyResearchRunStep).where(CompanyResearchRunStep.id == step_id).with_for_update()
        )
        step = result.scalar_one_or_none()
        if not step:
            return None
        step.status = "failed"
        step.last_error = last_error
        step.finished_at = utc_now()
        step.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
        await self.db.flush()
        await self.db.refresh(step)
        return step

    async def mark_step_cancelled(self, step_id: UUID, reason: Optional[str] = None) -> Optional[CompanyResearchRunStep]:
        result = await self.db.execute(
            select(CompanyResearchRunStep).where(CompanyResearchRunStep.id == step_id).with_for_update()
        )
        step = result.scalar_one_or_none()
        if not step:
            return None
        step.status = "cancelled"
        step.last_error = reason
        step.finished_at = utc_now()
        await self.db.flush()
        await self.db.refresh(step)
        return step

    async def cancel_pending_steps(self, tenant_id: str, run_id: UUID, reason: Optional[str] = None) -> int:
        result = await self.db.execute(
            select(CompanyResearchRunStep).where(
                CompanyResearchRunStep.tenant_id == tenant_id,
                CompanyResearchRunStep.run_id == run_id,
                CompanyResearchRunStep.status.in_(["pending", "running", "failed"]),
            )
        )
        steps = result.scalars().all()
        count = 0
        for step in steps:
            if step.status != "succeeded":
                step.status = "cancelled"
                step.last_error = reason
                step.finished_at = utc_now()
                count += 1
        await self.db.flush()
        return count

    async def request_cancel_job(self, tenant_id: str, run_id: UUID) -> bool:
        result = await self.db.execute(
            select(CompanyResearchJob)
            .where(
                CompanyResearchJob.tenant_id == tenant_id,
                CompanyResearchJob.run_id == run_id,
                CompanyResearchJob.status.in_(["queued", "running"]),
            )
            .with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return False
        job.cancel_requested = True
        await self.db.flush()
        return True

    async def claim_next_job(self, worker_id: str) -> Optional[CompanyResearchJob]:
        now = func.now()
        result = await self.db.execute(
            select(CompanyResearchJob)
            .where(
                CompanyResearchJob.status.in_(["queued", "failed", "running"]),
                CompanyResearchJob.attempt_count < CompanyResearchJob.max_attempts,
                or_(
                    CompanyResearchJob.next_retry_at.is_(None),
                    CompanyResearchJob.next_retry_at <= now,
                ),
                or_(
                    CompanyResearchJob.status != "running",
                    CompanyResearchJob.locked_at.is_(None),
                ),
            )
            .order_by(CompanyResearchJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if not job:
            return None

        job.locked_by = worker_id
        job.locked_at = utc_now()
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def mark_job_running(self, job_id: UUID, worker_id: str) -> Optional[CompanyResearchJob]:
        result = await self.db.execute(
            select(CompanyResearchJob).where(CompanyResearchJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return None

        increment_attempt = job.status != "running"
        job.status = "running"
        if increment_attempt:
            job.attempt_count = job.attempt_count + 1
        job.locked_by = worker_id
        job.locked_at = utc_now()
        job.next_retry_at = None
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def mark_job_succeeded(self, job_id: UUID) -> Optional[CompanyResearchJob]:
        result = await self.db.execute(
            select(CompanyResearchJob).where(CompanyResearchJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return None
        job.status = "succeeded"
        job.locked_at = None
        job.locked_by = None
        job.cancel_requested = False
        job.last_error = None
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def mark_job_cancelled(self, job_id: UUID, last_error: Optional[str] = None) -> Optional[CompanyResearchJob]:
        result = await self.db.execute(
            select(CompanyResearchJob).where(CompanyResearchJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return None
        job.status = "cancelled"
        job.last_error = last_error
        job.locked_at = None
        job.locked_by = None
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def mark_job_failed(
        self,
        job_id: UUID,
        last_error: str,
        backoff_seconds: int = 30,
    ) -> Optional[CompanyResearchJob]:
        result = await self.db.execute(
            select(CompanyResearchJob).where(CompanyResearchJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if not job:
            return None

        job.status = "failed"
        job.last_error = last_error
        job.locked_at = None
        job.locked_by = None
        job.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_job(self, job_id: UUID) -> Optional[CompanyResearchJob]:
        result = await self.db.execute(select(CompanyResearchJob).where(CompanyResearchJob.id == job_id))
        return result.scalar_one_or_none()

    async def append_research_event(
        self,
        tenant_id: str,
        run_id: UUID,
        event_type: str,
        message: str,
        meta_json: Optional[dict] = None,
        status: str = "ok",
    ) -> CompanyResearchEvent:
        return await self.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type=event_type,
                status=status,
                input_json=meta_json,
                output_json={"message": message} if message else None,
                error_message=message if status == "failed" else None,
            ),
        )

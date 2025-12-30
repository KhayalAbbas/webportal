"""
Company Research repository - database operations.

Handles CRUD operations for company discovery and agentic sourcing.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select, func, desc, asc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.company_research import (
    CompanyResearchRun,
    CompanyProspect,
    CompanyProspectEvidence,
    CompanyProspectMetric,
    ResearchSourceDocument,
    CompanyResearchEvent,
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
            status="new",  # Explicitly set initial status
            **data.model_dump(),
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
    
    async def get_processable_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> List[ResearchSourceDocument]:
        """Get sources that need processing (new or fetched status)."""
        result = await self.db.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.company_research_run_id == run_id,
                ResearchSourceDocument.status.in_(['new', 'fetched']),
            )
            .order_by(ResearchSourceDocument.created_at)
        )
        return list(result.scalars().all())
    
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

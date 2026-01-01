"""
Company Research Router - API endpoints.

Provides REST API for company discovery and agentic sourcing.
Phase 1: Backend structures, no external AI orchestration yet.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.services.company_research_service import CompanyResearchService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyResearchRunRead,
    CompanyResearchRunUpdate,
    CompanyResearchRunSummary,
    CompanyResearchJobRead,
    CompanyResearchRunPlanRead,
    CompanyResearchRunStepRead,
    CompanyProspectCreate,
    CompanyProspectRead,
    CompanyProspectListItem,
    CompanyProspectWithEvidence,
    CompanyProspectUpdateManual,
    CompanyProspectEvidenceCreate,
    CompanyProspectEvidenceRead,
    CompanyProspectMetricCreate,
    CompanyProspectMetricRead,
    ResearchEventRead,
    SourceDocumentRead,
    SourceDocumentCreate,
)

router = APIRouter(prefix="/company-research", tags=["company-research"])


class ManualListSourcePayload(BaseModel):
    title: Optional[str] = None
    content_text: str


class ProposalSourcePayload(BaseModel):
    title: Optional[str] = None
    content_text: str


# ============================================================================
# Research Run Endpoints
# ============================================================================


@router.get("/runs", response_model=List[CompanyResearchRunRead])
async def list_research_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List research runs for the tenant."""
    service = CompanyResearchService(db)
    runs = await service.list_research_runs(
        tenant_id=current_user.tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [CompanyResearchRunRead.model_validate(r) for r in runs]

@router.post("/runs", response_model=CompanyResearchRunRead)
async def create_research_run(
    data: CompanyResearchRunCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new company research run for a specific role/mandate.
    
    This initializes a discovery exercise with optional ranking and enrichment config.
    """
    service = CompanyResearchService(db)
    
    run = await service.create_research_run(
        tenant_id=current_user.tenant_id,
        data=data,
        created_by_user_id=current_user.id,
    )
    
    await db.commit()
    return CompanyResearchRunRead.model_validate(run)


@router.get("/runs/{run_id}", response_model=CompanyResearchRunSummary)
async def get_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a research run by ID with prospect count summary.
    """
    service = CompanyResearchService(db)
    
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospect_count = await service.count_prospects_for_run(current_user.tenant_id, run_id)
    
    # Build summary response
    run_dict = {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "role_mandate_id": run.role_mandate_id,
        "name": run.name,
        "description": run.description,
        "status": run.status,
        "sector": run.sector,
        "region_scope": getattr(run, "region_scope", None),
        "config": run.config,
        "summary": getattr(run, "summary", None),
        "last_error": getattr(run, "last_error", None),
        "created_by_user_id": run.created_by_user_id,
        "started_at": getattr(run, "started_at", None),
        "finished_at": getattr(run, "finished_at", None),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "prospect_count": prospect_count,
    }
    
    return CompanyResearchRunSummary(**run_dict)


@router.get("/runs/{run_id}/plan", response_model=CompanyResearchRunPlanRead)
async def get_research_run_plan(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Get or build the deterministic plan for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    plan, _ = await service.ensure_plan_and_steps(current_user.tenant_id, run_id)
    return CompanyResearchRunPlanRead.model_validate(plan)


@router.get("/runs/{run_id}/steps", response_model=List[CompanyResearchRunStepRead])
async def list_research_run_steps(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List deterministic steps for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    _, steps = await service.ensure_plan_and_steps(current_user.tenant_id, run_id)
    return [CompanyResearchRunStepRead.model_validate(s) for s in steps]


@router.post("/runs/{run_id}/start", response_model=CompanyResearchJobRead)
async def start_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue a research run for processing."""
    service = CompanyResearchService(db)
    try:
        job = await service.start_run(current_user.tenant_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Research run not found")
    await db.commit()
    return CompanyResearchJobRead.model_validate(job)


@router.post("/runs/{run_id}/sources/list", response_model=SourceDocumentRead)
async def add_manual_list_source(
    run_id: UUID,
    payload: ManualListSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach a manual list source document to a run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="manual_list",
            title=payload.title or "Manual List",
            content_text=payload.content_text,
            meta={"kind": "list", "source_name": payload.title or "manual_list", "submitted_via": "api"},
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/sources/proposal", response_model=SourceDocumentRead)
async def add_proposal_source(
    run_id: UUID,
    payload: ProposalSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach an AI proposal JSON payload as a source document for ingestion."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="ai_proposal",
            title=payload.title or "AI Proposal",
            content_text=payload.content_text,
            meta={"kind": "proposal", "submitted_via": "api"},
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/retry", response_model=CompanyResearchJobRead)
async def retry_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Retry a research run by enqueuing a new job (idempotent)."""
    service = CompanyResearchService(db)
    try:
        job = await service.retry_run(current_user.tenant_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Research run not found")
    await db.commit()
    return CompanyResearchJobRead.model_validate(job)


@router.post("/runs/{run_id}/cancel")
async def cancel_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Request cancellation for a research run job."""
    service = CompanyResearchService(db)
    result = await service.cancel_run(current_user.tenant_id, run_id)
    await db.commit()

    if result == "not_found":
        raise HTTPException(status_code=404, detail="Research run not found")
    if result == "noop_terminal":
        raise HTTPException(status_code=409, detail="Run already completed")
    if result == "no_active_job":
        raise HTTPException(status_code=404, detail="Active job not found")

    return {"status": "cancel_requested"}


@router.get("/runs/{run_id}/events", response_model=List[ResearchEventRead])
async def list_research_events(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List recent events for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    events = await service.list_events_for_run(current_user.tenant_id, run_id, limit=limit)
    return [ResearchEventRead.model_validate(e) for e in events]


@router.get("/runs/{run_id}/prospects", response_model=List[CompanyProspectListItem])
async def list_prospects_for_run(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    order_by: str = Query("ai", description="Ordering mode: 'ai' (relevance) or 'manual' (user priority)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List company prospects for a research run.
    
    Supports filtering by status, minimum relevance score, and ordering by AI or manual ranking.
    
    Ordering modes:
    - "ai": Pinned first, then by AI relevance_score DESC
    - "manual": Pinned first, then by manual_priority ASC (1=highest) NULLS LAST, then relevance
    """
    service = CompanyResearchService(db)
    
    # Verify run exists and belongs to tenant
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospects = await service.list_prospects_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    
    return [CompanyProspectListItem.model_validate(p) for p in prospects]


@router.get("/runs/{run_id}/prospects-with-evidence", response_model=List[CompanyProspectWithEvidence])
async def list_prospects_for_run_with_evidence(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    order_by: str = Query("ai", description="Ordering mode: 'ai' (relevance) or 'manual' (user priority)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List company prospects for a research run with evidence and source document details.
    
    Returns prospects with nested evidence records and their linked source documents.
    Uses efficient joins to avoid N+1 queries.
    
    Ordering modes:
    - "ai": Pinned first, then by AI relevance_score DESC
    - "manual": Pinned first, then by manual_priority ASC (1=highest) NULLS LAST, then relevance
    """
    service = CompanyResearchService(db)
    
    # Verify run exists and belongs to tenant
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospects = await service.list_prospects_for_run_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    
    return [CompanyProspectWithEvidence.model_validate(p) for p in prospects]


@router.patch("/runs/{run_id}", response_model=CompanyResearchRunRead)
async def update_research_run(
    run_id: UUID,
    data: CompanyResearchRunUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a research run (status, description, config, etc.).
    """
    service = CompanyResearchService(db)
    
    run = await service.update_research_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        data=data,
    )
    
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    await db.commit()
    return CompanyResearchRunRead.model_validate(run)


# ============================================================================
# Company Prospect Endpoints
# ============================================================================

@router.post("/prospects", response_model=CompanyProspectRead)
async def create_prospect(
    data: CompanyProspectCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new company prospect (typically called by AI/system).
    """
    service = CompanyResearchService(db)
    
    prospect = await service.create_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectRead.model_validate(prospect)


@router.get("/prospects/{prospect_id}", response_model=CompanyProspectRead)
async def get_prospect(
    prospect_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a company prospect by ID.
    """
    service = CompanyResearchService(db)
    
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    return CompanyProspectRead.model_validate(prospect)


@router.patch("/prospects/{prospect_id}/manual", response_model=CompanyProspectRead)
async def update_prospect_manual_fields(
    prospect_id: UUID,
    data: CompanyProspectUpdateManual,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update manual override fields for a company prospect.
    
    This endpoint ONLY updates:
    - manual_priority (1 = highest priority)
    - manual_notes
    - is_pinned
    - status
    
    AI-calculated fields (relevance_score, evidence_score) are NEVER touched by this endpoint.
    """
    service = CompanyResearchService(db)
    
    prospect = await service.update_prospect_manual_fields(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        data=data,
    )
    
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    await db.commit()
    return CompanyProspectRead.model_validate(prospect)


# ============================================================================
# Evidence Endpoints
# ============================================================================

@router.post("/prospects/{prospect_id}/evidence", response_model=CompanyProspectEvidenceRead)
async def add_evidence_to_prospect(
    prospect_id: UUID,
    data: CompanyProspectEvidenceCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Add evidence to a company prospect.
    
    Evidence sources: ranking_list, association_directory, regulatory_register, etc.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    # Ensure evidence belongs to the correct prospect
    data.company_prospect_id = prospect_id
    
    evidence = await service.add_evidence_to_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectEvidenceRead.model_validate(evidence)


@router.get("/prospects/{prospect_id}/evidence", response_model=List[CompanyProspectEvidenceRead])
async def list_evidence_for_prospect(
    prospect_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List all evidence records for a specific company prospect.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    evidence_list = await service.list_evidence_for_prospect(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
    )
    
    return [CompanyProspectEvidenceRead.model_validate(e) for e in evidence_list]


# ============================================================================
# Metric Endpoints
# ============================================================================

@router.post("/prospects/{prospect_id}/metrics", response_model=CompanyProspectMetricRead)
async def add_metric_to_prospect(
    prospect_id: UUID,
    data: CompanyProspectMetricCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a metric to a company prospect.
    
    Metrics: total_assets, revenue, employees, etc. with currency conversion to USD.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    # Ensure metric belongs to the correct prospect
    data.company_prospect_id = prospect_id
    
    metric = await service.add_metric_to_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectMetricRead.model_validate(metric)


@router.get("/prospects/{prospect_id}/metrics", response_model=List[CompanyProspectMetricRead])
async def list_metrics_for_prospect(
    prospect_id: UUID,
    metric_type: Optional[str] = Query(None, description="Filter by metric type (total_assets, revenue, employees, etc.)"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List all metrics for a specific company prospect.
    
    Optionally filter by metric_type.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    metrics = await service.list_metrics_for_prospect(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        metric_type=metric_type,
    )
    
    return [CompanyProspectMetricRead.model_validate(m) for m in metrics]


# ============================================================================
# DEV/TEST ENDPOINTS - Remove in production
# ============================================================================

@router.post("/runs/{run_id}/seed-dummy-prospects", response_model=List[CompanyProspectRead])
async def seed_dummy_prospects(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    [DEV ONLY] Create 5 dummy company prospects for testing.
    
    This endpoint creates realistic fake data to test listing and sorting logic.
    Remove or protect this endpoint in production.
    """
    service = CompanyResearchService(db)
    
    # Verify run exists
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Create 5 dummy prospects with varied scores and priorities
    dummy_data = [
        {
            "name": "ABC Financial Services Ltd",
            "website": "https://abcfinancial.example.com",
            "headquarters_location": "Mumbai, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Leading NBFC specializing in vehicle financing",
            "relevance_score": 0.92,
            "evidence_score": 0.88,
            "manual_priority": None,
            "is_pinned": False,
        },
        {
            "name": "XYZ Capital & Investments",
            "website": "https://xyzcapital.example.com",
            "headquarters_location": "Bangalore, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Mid-sized NBFC focused on SME lending",
            "relevance_score": 0.85,
            "evidence_score": 0.82,
            "manual_priority": 3,
            "is_pinned": False,
        },
        {
            "name": "Premier Finance Corporation",
            "website": "https://premierfinance.example.com",
            "headquarters_location": "Delhi, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Large NBFC with strong retail presence",
            "relevance_score": 0.78,
            "evidence_score": 0.75,
            "manual_priority": 2,
            "is_pinned": False,
        },
        {
            "name": "Strategic NBFC Holdings",
            "website": "https://strategicnbfc.example.com",
            "headquarters_location": "Pune, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Key strategic NBFC with diversified portfolio",
            "relevance_score": 0.71,
            "evidence_score": 0.68,
            "manual_priority": 1,
            "is_pinned": True,
        },
        {
            "name": "Omega Credit Solutions",
            "website": "https://omegacredit.example.com",
            "headquarters_location": "Chennai, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Emerging NBFC in microfinance sector",
            "relevance_score": 0.65,
            "evidence_score": 0.61,
            "manual_priority": None,
            "is_pinned": False,
        },
    ]
    
    created_prospects = []
    for data in dummy_data:
        prospect_create = CompanyProspectCreate(
            company_research_run_id=run_id,
            name=data["name"],
            name_normalized=data["name"].lower().replace("ltd", "").replace(".", "").strip(),
            website=data["website"],
            headquarters_location=data["headquarters_location"],
            country_code=data["country_code"],
            industry_sector=data["industry_sector"],
            brief_description=data["brief_description"],
            relevance_score=data["relevance_score"],
            evidence_score=data["evidence_score"],
            manual_priority=data["manual_priority"],
            is_pinned=data["is_pinned"],
            status="new",
        )
        
        prospect = await service.create_prospect(
            tenant_id=current_user.tenant_id,
            data=prospect_create,
        )
        created_prospects.append(prospect)
    
    await db.commit()
    
    return [CompanyProspectRead.model_validate(p) for p in created_prospects]

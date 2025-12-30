"""
Candidate router - API endpoints for candidates.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id, verify_user_tenant_access
from app.models.user import User
from app.schemas.candidate import CandidateCreate, CandidateRead, CandidateUpdate
from app.schemas.entity_research import EntityResearchData
from app.services.candidate_service import CandidateService
from app.services.entity_research_service import EntityResearchService

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("", response_model=List[CandidateRead])
async def list_candidates(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_title: Optional[str] = None,
    current_company: Optional[str] = None,
    home_country: Optional[str] = None,
):
    """
    List candidates with pagination and filters.
    
    Filters: current_title, current_company, home_country.
    """
    service = CandidateService(db)
    candidates = await service.list_candidates(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        current_title=current_title,
        current_company=current_company,
        home_country=home_country,
    )
    return candidates


@router.get("/{candidate_id}", response_model=CandidateRead)
async def get_candidate(
    candidate_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a candidate by ID."""
    service = CandidateService(db)
    candidate = await service.get_candidate(tenant_id, candidate_id)
    
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found for this tenant"
        )
    
    return candidate


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    data: CandidateCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new candidate."""
    service = CandidateService(db)
    candidate = await service.create_candidate(tenant_id, data)
    await db.commit()
    return candidate


@router.put("/{candidate_id}", response_model=CandidateRead)
async def update_candidate(
    candidate_id: UUID,
    data: CandidateUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a candidate."""
    service = CandidateService(db)
    candidate = await service.update_candidate(tenant_id, candidate_id, data)
    
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found for this tenant"
        )
    
    await db.commit()
    return candidate


@router.get("/{candidate_id}/research", response_model=EntityResearchData)
async def get_candidate_research(
    candidate_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all research data for a candidate.
    
    Returns:
    - All research events for this candidate
    - All source documents attached to those events
    - All AI enrichment records for this candidate
    """
    # Verify candidate exists and belongs to tenant
    candidate_service = CandidateService(db)
    candidate = await candidate_service.get_candidate(str(current_user.tenant_id), candidate_id)
    
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate not found"
        )
    
    research_service = EntityResearchService(db)
    return await research_service.get_entity_research(
        tenant_id=current_user.tenant_id,
        entity_type="CANDIDATE",
        entity_id=candidate_id
    )

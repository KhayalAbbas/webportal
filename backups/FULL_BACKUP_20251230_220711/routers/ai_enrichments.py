"""
AI Enrichments router - store and retrieve AI-generated insights.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.ai_enrichment import AIEnrichmentCreate, AIEnrichmentRead, AIEnrichmentUpdate
from app.services.ai_enrichment_service import AIEnrichmentService

router = APIRouter(prefix="/ai-enrichments", tags=["AI Enrichments"])


@router.get("/", response_model=list[AIEnrichmentRead])
async def list_ai_enrichments(
    current_user: User = Depends(verify_user_tenant_access),
    target_type: Optional[str] = Query(None, description="Filter by target type: CANDIDATE, COMPANY, ROLE, DOCUMENT"),
    target_id: Optional[UUID] = Query(None, description="Filter by target ID"),
    enrichment_type: Optional[str] = Query(None, description="Filter by type: SUMMARY, COMPETENCY_MAP, TAGGING, RISK_FLAGS, OTHER"),
    model_name: Optional[str] = Query(None, description="Filter by AI model name"),
    date_from: Optional[datetime] = Query(None, description="Filter enrichments from this date"),
    date_to: Optional[datetime] = Query(None, description="Filter enrichments until this date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List AI enrichment records with optional filters.
    
    All enrichments are scoped to the authenticated user's tenant.
    """
    service = AIEnrichmentService(db)
    return await service.get_by_tenant(
        tenant_id=current_user.tenant_id,
        target_type=target_type,
        target_id=target_id,
        enrichment_type=enrichment_type,
        model_name=model_name,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit
    )


@router.get("/{enrichment_id}", response_model=AIEnrichmentRead)
async def get_ai_enrichment(
    enrichment_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific AI enrichment record by ID.
    
    Only returns the enrichment if it belongs to the user's tenant.
    """
    service = AIEnrichmentService(db)
    enrichment = await service.get_by_id(current_user.tenant_id, enrichment_id)
    
    if not enrichment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI enrichment record not found"
        )
    
    return enrichment


@router.post("/", response_model=AIEnrichmentRead, status_code=status.HTTP_201_CREATED)
async def create_ai_enrichment(
    enrichment_data: AIEnrichmentCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new AI enrichment record.
    
    The enrichment will be associated with the authenticated user's tenant.
    Use this endpoint to store AI-generated insights, summaries, or analyses.
    """
    service = AIEnrichmentService(db)
    return await service.create(current_user.tenant_id, enrichment_data)


@router.patch("/{enrichment_id}", response_model=AIEnrichmentRead)
async def update_ai_enrichment(
    enrichment_id: UUID,
    enrichment_data: AIEnrichmentUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an AI enrichment record.
    
    Only enrichments belonging to the user's tenant can be updated.
    """
    service = AIEnrichmentService(db)
    updated_enrichment = await service.update(current_user.tenant_id, enrichment_id, enrichment_data)
    
    if not updated_enrichment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI enrichment record not found"
        )
    
    return updated_enrichment


@router.delete("/{enrichment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_enrichment(
    enrichment_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an AI enrichment record.
    
    Only enrichments belonging to the user's tenant can be deleted.
    """
    service = AIEnrichmentService(db)
    deleted = await service.delete(current_user.tenant_id, enrichment_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI enrichment record not found"
        )

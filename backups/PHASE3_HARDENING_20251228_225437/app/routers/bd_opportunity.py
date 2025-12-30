"""
BDOpportunity router - API endpoints for BD opportunities.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id
from app.schemas.bd_opportunity import (
    BDOpportunityCreate,
    BDOpportunityRead,
    BDOpportunityUpdate,
)
from app.services.bd_opportunity_service import BDOpportunityService

router = APIRouter(prefix="/bd-opportunities", tags=["bd-opportunities"])


@router.get("", response_model=List[BDOpportunityRead])
async def list_opportunities(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    company_id: Optional[UUID] = None,
    stage: Optional[str] = None,
):
    """
    List BD opportunities with pagination and filters.
    
    Filters: status, company_id, stage.
    """
    service = BDOpportunityService(db)
    opportunities = await service.list_opportunities(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        company_id=company_id,
        stage=stage,
    )
    return opportunities


@router.get("/{opportunity_id}", response_model=BDOpportunityRead)
async def get_opportunity(
    opportunity_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a BD opportunity by ID."""
    service = BDOpportunityService(db)
    opportunity = await service.get_opportunity(tenant_id, opportunity_id)
    
    if not opportunity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Opportunity {opportunity_id} not found for this tenant"
        )
    
    return opportunity


@router.post("", response_model=BDOpportunityRead, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    data: BDOpportunityCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new BD opportunity."""
    service = BDOpportunityService(db)
    opportunity = await service.create_opportunity(tenant_id, data)
    await db.commit()
    return opportunity


@router.put("/{opportunity_id}", response_model=BDOpportunityRead)
async def update_opportunity(
    opportunity_id: UUID,
    data: BDOpportunityUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a BD opportunity."""
    service = BDOpportunityService(db)
    opportunity = await service.update_opportunity(tenant_id, opportunity_id, data)
    
    if not opportunity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Opportunity {opportunity_id} not found for this tenant"
        )
    
    await db.commit()
    return opportunity

"""
Company router - API endpoints for companies.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id, verify_user_tenant_access
from app.models.user import User
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate
from app.schemas.entity_research import EntityResearchData
from app.services.company_service import CompanyService
from app.services.entity_research_service import EntityResearchService

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=List[CompanyRead])
async def list_companies(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    bd_status: Optional[str] = None,
    bd_owner: Optional[str] = None,
    is_client: Optional[bool] = None,
    is_prospect: Optional[bool] = None,
):
    """
    List companies with pagination and filters.
    
    Filters: bd_status, bd_owner, is_client, is_prospect.
    """
    service = CompanyService(db)
    companies = await service.list_companies(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        bd_status=bd_status,
        bd_owner=bd_owner,
        is_client=is_client,
        is_prospect=is_prospect,
    )
    return companies


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a company by ID."""
    service = CompanyService(db)
    company = await service.get_company(tenant_id, company_id)
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found for this tenant"
        )
    
    return company


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    data: CompanyCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new company."""
    service = CompanyService(db)
    company = await service.create_company(tenant_id, data)
    await db.commit()
    return company


@router.put("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: UUID,
    data: CompanyUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a company."""
    service = CompanyService(db)
    company = await service.update_company(tenant_id, company_id, data)
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found for this tenant"
        )
    
    await db.commit()
    return company


@router.get("/{company_id}/research", response_model=EntityResearchData)
async def get_company_research(
    company_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all research data for a company.
    
    Returns:
    - All research events for this company
    - All source documents attached to those events
    - All AI enrichment records for this company
    """
    # Verify company exists and belongs to tenant
    company_service = CompanyService(db)
    company = await company_service.get_company(str(current_user.tenant_id), company_id)
    
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    research_service = EntityResearchService(db)
    return await research_service.get_entity_research(
        tenant_id=current_user.tenant_id,
        entity_type="COMPANY",
        entity_id=company_id
    )

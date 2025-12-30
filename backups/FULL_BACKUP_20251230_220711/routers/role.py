"""
Role router - API endpoints for roles.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id, verify_user_tenant_access
from app.models.user import User
from app.schemas.role import RoleCreate, RoleRead, RoleUpdate
from app.schemas.entity_research import EntityResearchData
from app.services.role_service import RoleService
from app.services.entity_research_service import EntityResearchService

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=List[RoleRead])
async def list_roles(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    company_id: Optional[UUID] = None,
):
    """
    List roles with pagination and filters.
    
    Filters: status, company_id.
    """
    service = RoleService(db)
    roles = await service.list_roles(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        company_id=company_id,
    )
    return roles


@router.get("/{role_id}", response_model=RoleRead)
async def get_role(
    role_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a role by ID."""
    service = RoleService(db)
    role = await service.get_role(tenant_id, role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role {role_id} not found for this tenant"
        )
    
    return role


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new role."""
    service = RoleService(db)
    role = await service.create_role(tenant_id, data)
    await db.commit()
    return role


@router.put("/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: UUID,
    data: RoleUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a role."""
    service = RoleService(db)
    role = await service.update_role(tenant_id, role_id, data)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role {role_id} not found for this tenant"
        )
    
    await db.commit()
    return role


@router.get("/{role_id}/research", response_model=EntityResearchData)
async def get_role_research(
    role_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all research data for a role.
    
    Returns:
    - All research events for this role
    - All source documents attached to those events
    - All AI enrichment records for this role
    """
    # Verify role exists and belongs to tenant
    role_service = RoleService(db)
    role = await role_service.get_role(str(current_user.tenant_id), role_id)
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found"
        )
    
    research_service = EntityResearchService(db)
    return await research_service.get_entity_research(
        tenant_id=current_user.tenant_id,
        entity_type="ROLE",
        entity_id=role_id
    )

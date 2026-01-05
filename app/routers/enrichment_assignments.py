"""
Read-only enrichment assignment endpoints for canonical entities.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.enrichment_assignment import EnrichmentAssignmentRead
from app.services.enrichment_assignment_service import EnrichmentAssignmentService

router = APIRouter(prefix="/enrichment-assignments", tags=["Enrichment Assignments"])


@router.get("/canonical-companies/{canonical_company_id}", response_model=list[EnrichmentAssignmentRead])
async def list_company_enrichment_assignments(
    canonical_company_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List enrichment assignments for a canonical company (tenant-scoped)."""
    service = EnrichmentAssignmentService(db)
    return await service.list_for_canonical_company(current_user.tenant_id, canonical_company_id)


@router.get("/canonical-people/{canonical_person_id}", response_model=list[EnrichmentAssignmentRead])
async def list_person_enrichment_assignments(
    canonical_person_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List enrichment assignments for a canonical person (tenant-scoped)."""
    service = EnrichmentAssignmentService(db)
    return await service.list_for_canonical_person(current_user.tenant_id, canonical_person_id)

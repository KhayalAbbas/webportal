"""
CandidateAssignment router - API endpoints for candidate assignments.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.dependencies import get_db, get_tenant_id
from app.schemas.candidate_assignment import (
    CandidateAssignmentCreate,
    CandidateAssignmentRead,
    CandidateAssignmentUpdate,
)
from app.services.candidate_assignment_service import CandidateAssignmentService

router = APIRouter(prefix="/candidate-assignments", tags=["candidate-assignments"])


class AssignRequest(BaseModel):
    """Request to assign a candidate to a role."""
    candidate_id: UUID
    role_id: UUID
    initial_status: Optional[str] = "pending"
    source: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    """Request to update assignment status."""
    new_status: str
    current_stage_id: Optional[UUID] = None


@router.get("", response_model=List[CandidateAssignmentRead])
async def list_assignments(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    is_hot: Optional[bool] = None,
):
    """
    List candidate assignments with pagination and filters.
    
    Filters: status, is_hot.
    """
    service = CandidateAssignmentService(db)
    assignments = await service.list_assignments(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        is_hot=is_hot,
    )
    return assignments


@router.get("/{assignment_id}", response_model=CandidateAssignmentRead)
async def get_assignment(
    assignment_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get an assignment by ID."""
    service = CandidateAssignmentService(db)
    assignment = await service.get_assignment(tenant_id, assignment_id)
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment {assignment_id} not found for this tenant"
        )
    
    return assignment


@router.post("", response_model=CandidateAssignmentRead, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    data: CandidateAssignmentCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new candidate assignment."""
    service = CandidateAssignmentService(db)
    assignment = await service.create_assignment(tenant_id, data)
    await db.commit()
    return assignment


@router.post("/assign", response_model=CandidateAssignmentRead, status_code=status.HTTP_201_CREATED)
async def assign_candidate(
    request: AssignRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Helper endpoint to assign a candidate to a role.
    
    Creates a CandidateAssignment with the provided candidate_id, role_id, 
    initial status, and optional source.
    """
    service = CandidateAssignmentService(db)
    
    assignment_data = CandidateAssignmentCreate(
        tenant_id=tenant_id,
        candidate_id=request.candidate_id,
        role_id=request.role_id,
        status=request.initial_status,
        source=request.source,
    )
    
    assignment = await service.create_assignment(tenant_id, assignment_data)
    await db.commit()
    return assignment


@router.post("/{assignment_id}/status", response_model=CandidateAssignmentRead)
async def update_assignment_status(
    assignment_id: UUID,
    request: StatusUpdateRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the status and optionally the current stage of an assignment.
    """
    service = CandidateAssignmentService(db)
    
    update_data = CandidateAssignmentUpdate(
        status=request.new_status,
        current_stage_id=request.current_stage_id,
    )
    
    assignment = await service.update_assignment(tenant_id, assignment_id, update_data)
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment {assignment_id} not found for this tenant"
        )
    
    await db.commit()
    return assignment


@router.get("/by-role/{role_id}", response_model=List[CandidateAssignmentRead])
async def get_assignments_by_role(
    role_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get all candidate assignments for a specific role.
    
    Returns assignments with joined candidate basic info.
    """
    service = CandidateAssignmentService(db)
    assignments = await service.get_assignments_by_role(
        tenant_id=tenant_id,
        role_id=role_id,
        limit=limit,
        offset=offset,
    )
    return assignments


@router.get("/by-candidate/{candidate_id}", response_model=List[CandidateAssignmentRead])
async def get_assignments_by_candidate(
    candidate_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get all assignments for a specific candidate.
    
    Returns assignments with joined role basic info.
    """
    service = CandidateAssignmentService(db)
    assignments = await service.get_assignments_by_candidate(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        limit=limit,
        offset=offset,
    )
    return assignments


@router.put("/{assignment_id}", response_model=CandidateAssignmentRead)
async def update_assignment(
    assignment_id: UUID,
    data: CandidateAssignmentUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a candidate assignment."""
    service = CandidateAssignmentService(db)
    assignment = await service.update_assignment(tenant_id, assignment_id, data)
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assignment {assignment_id} not found for this tenant"
        )
    
    await db.commit()
    return assignment

"""
CandidateAssignment business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_assignment import CandidateAssignment
from app.schemas.candidate_assignment import (
    CandidateAssignmentCreate,
    CandidateAssignmentUpdate,
)
from app.repositories.candidate_assignment_repository import (
    CandidateAssignmentRepository
)


class CandidateAssignmentService:
    """Service for candidate assignment business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = CandidateAssignmentRepository(db)
    
    async def list_assignments(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        is_hot: Optional[bool] = None,
    ) -> List[CandidateAssignment]:
        """List assignments with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            status=status,
            is_hot=is_hot,
        )
    
    async def get_assignment(
        self,
        tenant_id: str,
        assignment_id: UUID
    ) -> Optional[CandidateAssignment]:
        """Get an assignment by ID."""
        return await self.repository.get_by_id(tenant_id, assignment_id)
    
    async def create_assignment(
        self,
        tenant_id: str,
        data: CandidateAssignmentCreate
    ) -> CandidateAssignment:
        """Create a new assignment."""
        return await self.repository.create(tenant_id, data)
    
    async def update_assignment(
        self,
        tenant_id: str,
        assignment_id: UUID,
        data: CandidateAssignmentUpdate
    ) -> Optional[CandidateAssignment]:
        """Update an assignment."""
        return await self.repository.update(tenant_id, assignment_id, data)
    
    async def get_assignments_by_role(
        self,
        tenant_id: str,
        role_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CandidateAssignment]:
        """Get all assignments for a role."""
        return await self.repository.get_by_role(tenant_id, role_id, limit, offset)
    
    async def get_assignments_by_candidate(
        self,
        tenant_id: str,
        candidate_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CandidateAssignment]:
        """Get all assignments for a candidate."""
        return await self.repository.get_by_candidate(
            tenant_id, candidate_id, limit, offset
        )

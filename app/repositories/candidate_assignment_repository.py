"""
CandidateAssignment repository - database operations for CandidateAssignment.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.candidate_assignment import CandidateAssignment
from app.schemas.candidate_assignment import (
    CandidateAssignmentCreate,
    CandidateAssignmentUpdate,
)


class CandidateAssignmentRepository:
    """Repository for CandidateAssignment database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        is_hot: Optional[bool] = None,
    ) -> List[CandidateAssignment]:
        """List assignments for a tenant with filters."""
        query = select(CandidateAssignment).where(
            CandidateAssignment.tenant_id == tenant_id
        )
        
        if status is not None:
            query = query.where(CandidateAssignment.status == status)
        if is_hot is not None:
            query = query.where(CandidateAssignment.is_hot == is_hot)
        
        query = query.order_by(CandidateAssignment.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(
        self,
        tenant_id: str,
        assignment_id: UUID
    ) -> Optional[CandidateAssignment]:
        """Get an assignment by ID for a specific tenant."""
        result = await self.db.execute(
            select(CandidateAssignment).where(
                CandidateAssignment.id == assignment_id,
                CandidateAssignment.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(
        self,
        tenant_id: str,
        data: CandidateAssignmentCreate
    ) -> CandidateAssignment:
        """Create a new assignment."""
        assignment = CandidateAssignment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(assignment)
        await self.db.flush()
        await self.db.refresh(assignment)
        return assignment
    
    async def update(
        self,
        tenant_id: str,
        assignment_id: UUID,
        data: CandidateAssignmentUpdate
    ) -> Optional[CandidateAssignment]:
        """Update an assignment."""
        assignment = await self.get_by_id(tenant_id, assignment_id)
        if not assignment:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(assignment, field, value)
        
        assignment.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(assignment)
        return assignment
    
    async def get_by_role(
        self,
        tenant_id: str,
        role_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CandidateAssignment]:
        """Get all assignments for a role."""
        result = await self.db.execute(
            select(CandidateAssignment)
            .where(
                CandidateAssignment.tenant_id == tenant_id,
                CandidateAssignment.role_id == role_id
            )
            .order_by(CandidateAssignment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
    
    async def get_by_candidate(
        self,
        tenant_id: str,
        candidate_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CandidateAssignment]:
        """Get all assignments for a candidate."""
        result = await self.db.execute(
            select(CandidateAssignment)
            .where(
                CandidateAssignment.tenant_id == tenant_id,
                CandidateAssignment.candidate_id == candidate_id
            )
            .order_by(CandidateAssignment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_candidate_and_role(
        self,
        tenant_id: str,
        candidate_id: UUID,
        role_id: UUID,
    ) -> Optional[CandidateAssignment]:
        """Get a single assignment for a candidate-role pair if it exists."""
        result = await self.db.execute(
            select(CandidateAssignment).where(
                CandidateAssignment.tenant_id == tenant_id,
                CandidateAssignment.candidate_id == candidate_id,
                CandidateAssignment.role_id == role_id,
            ).order_by(CandidateAssignment.created_at.asc())
        )
        return result.scalar_one_or_none()

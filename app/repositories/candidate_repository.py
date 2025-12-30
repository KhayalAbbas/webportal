"""
Candidate repository - database operations for Candidate.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.candidate import Candidate
from app.schemas.candidate import CandidateCreate, CandidateUpdate


class CandidateRepository:
    """Repository for Candidate database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        current_title: Optional[str] = None,
        current_company: Optional[str] = None,
        home_country: Optional[str] = None,
    ) -> List[Candidate]:
        """List candidates for a tenant with filters."""
        query = select(Candidate).where(Candidate.tenant_id == tenant_id)
        
        if current_title is not None:
            query = query.where(Candidate.current_title.ilike(f"%{current_title}%"))
        if current_company is not None:
            query = query.where(Candidate.current_company.ilike(f"%{current_company}%"))
        if home_country is not None:
            query = query.where(Candidate.home_country == home_country)
        
        query = query.order_by(
            Candidate.last_name.asc(),
            Candidate.first_name.asc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, candidate_id: UUID) -> Optional[Candidate]:
        """Get a candidate by ID for a specific tenant."""
        result = await self.db.execute(
            select(Candidate).where(
                Candidate.id == candidate_id,
                Candidate.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: CandidateCreate) -> Candidate:
        """Create a new candidate."""
        candidate = Candidate(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(candidate)
        await self.db.flush()
        await self.db.refresh(candidate)
        return candidate
    
    async def update(
        self,
        tenant_id: str,
        candidate_id: UUID,
        data: CandidateUpdate
    ) -> Optional[Candidate]:
        """Update a candidate."""
        candidate = await self.get_by_id(tenant_id, candidate_id)
        if not candidate:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(candidate, field, value)
        
        candidate.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(candidate)
        return candidate

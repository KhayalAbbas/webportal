"""
Candidate business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.schemas.candidate import CandidateCreate, CandidateUpdate
from app.repositories.candidate_repository import CandidateRepository


class CandidateService:
    """Service for candidate business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = CandidateRepository(db)
    
    async def list_candidates(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        current_title: Optional[str] = None,
        current_company: Optional[str] = None,
        home_country: Optional[str] = None,
    ) -> List[Candidate]:
        """List candidates with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            current_title=current_title,
            current_company=current_company,
            home_country=home_country,
        )
    
    async def get_candidate(self, tenant_id: str, candidate_id: UUID) -> Optional[Candidate]:
        """Get a candidate by ID."""
        return await self.repository.get_by_id(tenant_id, candidate_id)
    
    async def create_candidate(self, tenant_id: str, data: CandidateCreate) -> Candidate:
        """Create a new candidate."""
        return await self.repository.create(tenant_id, data)
    
    async def update_candidate(
        self,
        tenant_id: str,
        candidate_id: UUID,
        data: CandidateUpdate
    ) -> Optional[Candidate]:
        """Update a candidate."""
        return await self.repository.update(tenant_id, candidate_id, data)

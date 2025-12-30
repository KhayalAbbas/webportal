"""
BDOpportunity business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bd_opportunity import BDOpportunity
from app.schemas.bd_opportunity import BDOpportunityCreate, BDOpportunityUpdate
from app.repositories.bd_opportunity_repository import BDOpportunityRepository


class BDOpportunityService:
    """Service for BD opportunity business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = BDOpportunityRepository(db)
    
    async def list_opportunities(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        company_id: Optional[UUID] = None,
        stage: Optional[str] = None,
    ) -> List[BDOpportunity]:
        """List BD opportunities with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            status=status,
            company_id=company_id,
            stage=stage,
        )
    
    async def get_opportunity(
        self,
        tenant_id: str,
        opportunity_id: UUID
    ) -> Optional[BDOpportunity]:
        """Get an opportunity by ID."""
        return await self.repository.get_by_id(tenant_id, opportunity_id)
    
    async def create_opportunity(
        self,
        tenant_id: str,
        data: BDOpportunityCreate
    ) -> BDOpportunity:
        """Create a new opportunity."""
        return await self.repository.create(tenant_id, data)
    
    async def update_opportunity(
        self,
        tenant_id: str,
        opportunity_id: UUID,
        data: BDOpportunityUpdate
    ) -> Optional[BDOpportunity]:
        """Update an opportunity."""
        return await self.repository.update(tenant_id, opportunity_id, data)

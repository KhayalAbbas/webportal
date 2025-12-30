"""
BDOpportunity repository - database operations for BDOpportunity.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.bd_opportunity import BDOpportunity
from app.schemas.bd_opportunity import BDOpportunityCreate, BDOpportunityUpdate


class BDOpportunityRepository:
    """Repository for BDOpportunity database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        company_id: Optional[UUID] = None,
        stage: Optional[str] = None,
    ) -> List[BDOpportunity]:
        """List opportunities for a tenant with filters."""
        query = select(BDOpportunity).where(BDOpportunity.tenant_id == tenant_id)
        
        if status is not None:
            query = query.where(BDOpportunity.status == status)
        if company_id is not None:
            query = query.where(BDOpportunity.company_id == company_id)
        if stage is not None:
            query = query.where(BDOpportunity.stage == stage)
        
        query = query.order_by(BDOpportunity.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(
        self,
        tenant_id: str,
        opportunity_id: UUID
    ) -> Optional[BDOpportunity]:
        """Get an opportunity by ID for a specific tenant."""
        result = await self.db.execute(
            select(BDOpportunity).where(
                BDOpportunity.id == opportunity_id,
                BDOpportunity.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(
        self,
        tenant_id: str,
        data: BDOpportunityCreate
    ) -> BDOpportunity:
        """Create a new opportunity."""
        opportunity = BDOpportunity(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(opportunity)
        await self.db.flush()
        await self.db.refresh(opportunity)
        return opportunity
    
    async def update(
        self,
        tenant_id: str,
        opportunity_id: UUID,
        data: BDOpportunityUpdate
    ) -> Optional[BDOpportunity]:
        """Update an opportunity."""
        opportunity = await self.get_by_id(tenant_id, opportunity_id)
        if not opportunity:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(opportunity, field, value)
        
        opportunity.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(opportunity)
        return opportunity

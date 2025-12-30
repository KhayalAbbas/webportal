"""
Company repository - database operations for Company.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate


class CompanyRepository:
    """Repository for Company database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        bd_status: Optional[str] = None,
        bd_owner: Optional[str] = None,
        is_client: Optional[bool] = None,
        is_prospect: Optional[bool] = None,
    ) -> List[Company]:
        """List companies for a tenant with filters."""
        query = select(Company).where(Company.tenant_id == tenant_id)
        
        if bd_status is not None:
            query = query.where(Company.bd_status == bd_status)
        if bd_owner is not None:
            query = query.where(Company.bd_owner == bd_owner)
        if is_client is not None:
            query = query.where(Company.is_client == is_client)
        if is_prospect is not None:
            query = query.where(Company.is_prospect == is_prospect)
        
        query = query.order_by(Company.name.asc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, company_id: UUID) -> Optional[Company]:
        """Get a company by ID for a specific tenant."""
        result = await self.db.execute(
            select(Company).where(
                Company.id == company_id,
                Company.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: CompanyCreate) -> Company:
        """Create a new company."""
        company = Company(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(company)
        await self.db.flush()
        await self.db.refresh(company)
        return company
    
    async def update(
        self,
        tenant_id: str,
        company_id: UUID,
        data: CompanyUpdate
    ) -> Optional[Company]:
        """Update a company."""
        company = await self.get_by_id(tenant_id, company_id)
        if not company:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(company, field, value)
        
        company.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(company)
        return company

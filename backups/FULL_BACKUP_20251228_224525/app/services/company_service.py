"""
Company business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyUpdate
from app.repositories.company_repository import CompanyRepository


class CompanyService:
    """Service for company business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = CompanyRepository(db)
    
    async def list_companies(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        bd_status: Optional[str] = None,
        bd_owner: Optional[str] = None,
        is_client: Optional[bool] = None,
        is_prospect: Optional[bool] = None,
    ) -> List[Company]:
        """List companies with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            bd_status=bd_status,
            bd_owner=bd_owner,
            is_client=is_client,
            is_prospect=is_prospect,
        )
    
    async def get_company(self, tenant_id: str, company_id: UUID) -> Optional[Company]:
        """Get a company by ID."""
        return await self.repository.get_by_id(tenant_id, company_id)
    
    async def create_company(self, tenant_id: str, data: CompanyCreate) -> Company:
        """Create a new company."""
        return await self.repository.create(tenant_id, data)
    
    async def update_company(
        self,
        tenant_id: str,
        company_id: UUID,
        data: CompanyUpdate
    ) -> Optional[Company]:
        """Update a company."""
        return await self.repository.update(tenant_id, company_id, data)

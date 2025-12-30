"""
Role business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role
from app.schemas.role import RoleCreate, RoleUpdate
from app.repositories.role_repository import RoleRepository


class RoleService:
    """Service for role business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = RoleRepository(db)
    
    async def list_roles(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        company_id: Optional[UUID] = None,
    ) -> List[Role]:
        """List roles with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            status=status,
            company_id=company_id,
        )
    
    async def get_role(self, tenant_id: str, role_id: UUID) -> Optional[Role]:
        """Get a role by ID."""
        return await self.repository.get_by_id(tenant_id, role_id)
    
    async def create_role(self, tenant_id: str, data: RoleCreate) -> Role:
        """Create a new role."""
        return await self.repository.create(tenant_id, data)
    
    async def update_role(
        self,
        tenant_id: str,
        role_id: UUID,
        data: RoleUpdate
    ) -> Optional[Role]:
        """Update a role."""
        return await self.repository.update(tenant_id, role_id, data)

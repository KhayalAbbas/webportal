"""
Role repository - database operations for Role.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.role import Role
from app.schemas.role import RoleCreate, RoleUpdate


class RoleRepository:
    """Repository for Role database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        company_id: Optional[UUID] = None,
    ) -> List[Role]:
        """List roles for a tenant with filters."""
        query = select(Role).where(Role.tenant_id == tenant_id)
        
        if status is not None:
            query = query.where(Role.status == status)
        if company_id is not None:
            query = query.where(Role.company_id == company_id)
        
        query = query.order_by(Role.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, role_id: UUID) -> Optional[Role]:
        """Get a role by ID for a specific tenant."""
        result = await self.db.execute(
            select(Role).where(
                Role.id == role_id,
                Role.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: RoleCreate) -> Role:
        """Create a new role."""
        role = Role(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role
    
    async def update(
        self,
        tenant_id: str,
        role_id: UUID,
        data: RoleUpdate
    ) -> Optional[Role]:
        """Update a role."""
        role = await self.get_by_id(tenant_id, role_id)
        if not role:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(role, field, value)
        
        role.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(role)
        return role

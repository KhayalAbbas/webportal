"""
List repository - database operations for List.
"""

from typing import List as ListType, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.list import List
from app.schemas.list import ListCreate, ListUpdate


class ListRepository:
    """Repository for List database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        list_type: Optional[str] = None,
    ) -> ListType[List]:
        """List lists for a tenant with filters."""
        query = select(List).where(List.tenant_id == tenant_id)
        
        if list_type is not None:
            query = query.where(List.type == list_type)
        
        query = query.order_by(List.name.asc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, list_id: UUID) -> Optional[List]:
        """Get a list by ID for a specific tenant."""
        result = await self.db.execute(
            select(List).where(
                List.id == list_id,
                List.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: ListCreate) -> List:
        """Create a new list."""
        new_list = List(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(new_list)
        await self.db.flush()
        await self.db.refresh(new_list)
        return new_list
    
    async def update(
        self,
        tenant_id: str,
        list_id: UUID,
        data: ListUpdate
    ) -> Optional[List]:
        """Update a list."""
        list_obj = await self.get_by_id(tenant_id, list_id)
        if not list_obj:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(list_obj, field, value)
        
        list_obj.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(list_obj)
        return list_obj

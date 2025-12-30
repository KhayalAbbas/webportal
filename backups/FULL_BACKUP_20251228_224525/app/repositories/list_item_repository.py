"""
ListItem repository - database operations for ListItem.
"""

from typing import List as ListType, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.list_item import ListItem
from app.schemas.list_item import ListItemCreate, ListItemUpdate


class ListItemRepository:
    """Repository for ListItem database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        list_id: Optional[UUID] = None,
    ) -> ListType[ListItem]:
        """List items for a tenant with filters."""
        query = select(ListItem).where(ListItem.tenant_id == tenant_id)
        
        if list_id is not None:
            query = query.where(ListItem.list_id == list_id)
        
        query = query.order_by(ListItem.added_at.desc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, item_id: UUID) -> Optional[ListItem]:
        """Get an item by ID for a specific tenant."""
        result = await self.db.execute(
            select(ListItem).where(
                ListItem.id == item_id,
                ListItem.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: ListItemCreate) -> ListItem:
        """Create a new item."""
        item = ListItem(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item
    
    async def update(
        self,
        tenant_id: str,
        item_id: UUID,
        data: ListItemUpdate
    ) -> Optional[ListItem]:
        """Update an item."""
        item = await self.get_by_id(tenant_id, item_id)
        if not item:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        
        item.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(item)
        return item
    
    async def delete(self, tenant_id: str, item_id: UUID) -> bool:
        """Delete an item. Returns True if deleted, False if not found."""
        item = await self.get_by_id(tenant_id, item_id)
        if not item:
            return False
        
        await self.db.delete(item)
        await self.db.flush()
        return True

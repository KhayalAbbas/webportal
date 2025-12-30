"""
List and ListItem business logic service.
"""

from typing import List as ListType, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.list import List
from app.models.list_item import ListItem
from app.schemas.list import ListCreate, ListUpdate
from app.schemas.list_item import ListItemCreate, ListItemUpdate
from app.repositories.list_repository import ListRepository
from app.repositories.list_item_repository import ListItemRepository


class ListService:
    """Service for list business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = ListRepository(db)
    
    async def list_lists(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        list_type: Optional[str] = None,
    ) -> ListType[List]:
        """List lists with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            list_type=list_type,
        )
    
    async def get_list(self, tenant_id: str, list_id: UUID) -> Optional[List]:
        """Get a list by ID."""
        return await self.repository.get_by_id(tenant_id, list_id)
    
    async def create_list(self, tenant_id: str, data: ListCreate) -> List:
        """Create a new list."""
        return await self.repository.create(tenant_id, data)
    
    async def update_list(
        self,
        tenant_id: str,
        list_id: UUID,
        data: ListUpdate
    ) -> Optional[List]:
        """Update a list."""
        return await self.repository.update(tenant_id, list_id, data)


class ListItemService:
    """Service for list item business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = ListItemRepository(db)
    
    async def list_items(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        list_id: Optional[UUID] = None,
    ) -> ListType[ListItem]:
        """List items with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            list_id=list_id,
        )
    
    async def get_item(self, tenant_id: str, item_id: UUID) -> Optional[ListItem]:
        """Get an item by ID."""
        return await self.repository.get_by_id(tenant_id, item_id)
    
    async def create_item(self, tenant_id: str, data: ListItemCreate) -> ListItem:
        """Create a new item."""
        return await self.repository.create(tenant_id, data)
    
    async def update_item(
        self,
        tenant_id: str,
        item_id: UUID,
        data: ListItemUpdate
    ) -> Optional[ListItem]:
        """Update an item."""
        return await self.repository.update(tenant_id, item_id, data)

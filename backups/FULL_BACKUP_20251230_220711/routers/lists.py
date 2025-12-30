"""
List and ListItem routers - API endpoints for lists.
"""

from typing import List as ListType, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id
from app.schemas.list import ListCreate, ListRead, ListUpdate
from app.schemas.list_item import ListItemCreate, ListItemRead, ListItemUpdate
from app.services.list_service import ListService, ListItemService

list_router = APIRouter(prefix="/lists", tags=["lists"])
list_item_router = APIRouter(prefix="/list-items", tags=["list-items"])


# List endpoints
@list_router.get("", response_model=ListType[ListRead])
async def list_lists(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    list_type: Optional[str] = None,
):
    """
    List lists with pagination and filters.
    
    Filters: list_type.
    """
    service = ListService(db)
    lists = await service.list_lists(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        list_type=list_type,
    )
    return lists


@list_router.get("/{list_id}", response_model=ListRead)
async def get_list(
    list_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a list by ID."""
    service = ListService(db)
    list_obj = await service.get_list(tenant_id, list_id)
    
    if not list_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found for this tenant"
        )
    
    return list_obj


@list_router.post("", response_model=ListRead, status_code=status.HTTP_201_CREATED)
async def create_list(
    data: ListCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new list."""
    service = ListService(db)
    list_obj = await service.create_list(tenant_id, data)
    await db.commit()
    return list_obj


@list_router.put("/{list_id}", response_model=ListRead)
async def update_list(
    list_id: UUID,
    data: ListUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a list."""
    service = ListService(db)
    list_obj = await service.update_list(tenant_id, list_id, data)
    
    if not list_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List {list_id} not found for this tenant"
        )
    
    await db.commit()
    return list_obj


# ListItem endpoints
@list_item_router.get("", response_model=ListType[ListItemRead])
async def list_items(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    list_id: Optional[UUID] = None,
):
    """
    List items with pagination and filters.
    
    Filters: list_id.
    """
    service = ListItemService(db)
    items = await service.list_items(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        list_id=list_id,
    )
    return items


@list_item_router.get("/{item_id}", response_model=ListItemRead)
async def get_item(
    item_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a list item by ID."""
    service = ListItemService(db)
    item = await service.get_item(tenant_id, item_id)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List item {item_id} not found for this tenant"
        )
    
    return item


@list_item_router.post("", response_model=ListItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(
    data: ListItemCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new list item."""
    service = ListItemService(db)
    item = await service.create_item(tenant_id, data)
    await db.commit()
    return item


@list_item_router.put("/{item_id}", response_model=ListItemRead)
async def update_item(
    item_id: UUID,
    data: ListItemUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a list item."""
    service = ListItemService(db)
    item = await service.update_item(tenant_id, item_id, data)
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"List item {item_id} not found for this tenant"
        )
    
    await db.commit()
    return item

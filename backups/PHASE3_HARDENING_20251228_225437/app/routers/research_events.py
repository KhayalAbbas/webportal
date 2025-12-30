"""
Research Events router - track research activities on entities.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.research_event import ResearchEventCreate, ResearchEventRead, ResearchEventUpdate
from app.services.research_event_service import ResearchEventService

router = APIRouter(prefix="/research-events", tags=["Research Events"])


@router.get("/", response_model=list[ResearchEventRead])
async def list_research_events(
    current_user: User = Depends(verify_user_tenant_access),
    entity_type: Optional[str] = Query(None, description="Filter by entity type: CANDIDATE, COMPANY, ROLE"),
    entity_id: Optional[UUID] = Query(None, description="Filter by entity ID"),
    source_type: Optional[str] = Query(None, description="Filter by source: WEB, LINKEDIN, INTERNAL_DB, MANUAL, OTHER"),
    date_from: Optional[datetime] = Query(None, description="Filter events from this date"),
    date_to: Optional[datetime] = Query(None, description="Filter events until this date"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List research events with optional filters.
    
    All events are scoped to the authenticated user's tenant.
    """
    service = ResearchEventService(db)
    return await service.get_by_tenant(
        tenant_id=current_user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit
    )


@router.get("/{event_id}", response_model=ResearchEventRead)
async def get_research_event(
    event_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific research event by ID.
    
    Only returns the event if it belongs to the user's tenant.
    """
    service = ResearchEventService(db)
    event = await service.get_by_id(current_user.tenant_id, event_id)
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research event not found"
        )
    
    return event


@router.post("/", response_model=ResearchEventRead, status_code=status.HTTP_201_CREATED)
async def create_research_event(
    event_data: ResearchEventCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new research event.
    
    The event will be associated with the authenticated user's tenant.
    """
    service = ResearchEventService(db)
    return await service.create(current_user.tenant_id, event_data)


@router.patch("/{event_id}", response_model=ResearchEventRead)
async def update_research_event(
    event_id: UUID,
    event_data: ResearchEventUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a research event.
    
    Only events belonging to the user's tenant can be updated.
    """
    service = ResearchEventService(db)
    updated_event = await service.update(current_user.tenant_id, event_id, event_data)
    
    if not updated_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research event not found"
        )
    
    return updated_event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_research_event(
    event_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a research event.
    
    Only events belonging to the user's tenant can be deleted.
    """
    service = ResearchEventService(db)
    deleted = await service.delete(current_user.tenant_id, event_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research event not found"
        )

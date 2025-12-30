"""
Service layer for ResearchEvent business logic.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.research_event_repository import ResearchEventRepository
from app.schemas.research_event import ResearchEventCreate, ResearchEventUpdate, ResearchEventRead


class ResearchEventService:
    """Service for ResearchEvent business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ResearchEventRepository(db)
    
    async def get_by_id(self, tenant_id: UUID, event_id: UUID) -> Optional[ResearchEventRead]:
        """Get a research event by ID."""
        event = await self.repository.get_by_id(tenant_id, event_id)
        return ResearchEventRead.model_validate(event) if event else None
    
    async def get_by_tenant(
        self,
        tenant_id: UUID,
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        source_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50
    ) -> list[ResearchEventRead]:
        """Get research events with filters."""
        events = await self.repository.get_by_tenant(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            source_type=source_type,
            date_from=date_from,
            date_to=date_to,
            skip=skip,
            limit=limit
        )
        return [ResearchEventRead.model_validate(e) for e in events]
    
    async def create(self, tenant_id: UUID, data: ResearchEventCreate) -> ResearchEventRead:
        """Create a new research event."""
        event = await self.repository.create(tenant_id, data)
        await self.db.commit()
        return ResearchEventRead.model_validate(event)
    
    async def update(
        self,
        tenant_id: UUID,
        event_id: UUID,
        data: ResearchEventUpdate
    ) -> Optional[ResearchEventRead]:
        """Update a research event."""
        event = await self.repository.get_by_id(tenant_id, event_id)
        if not event:
            return None
        
        updated_event = await self.repository.update(event, data)
        await self.db.commit()
        return ResearchEventRead.model_validate(updated_event)
    
    async def delete(self, tenant_id: UUID, event_id: UUID) -> bool:
        """Delete a research event."""
        event = await self.repository.get_by_id(tenant_id, event_id)
        if not event:
            return False
        
        await self.repository.delete(event)
        await self.db.commit()
        return True

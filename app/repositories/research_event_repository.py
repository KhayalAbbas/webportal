"""
Repository for ResearchEvent database operations.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_event import ResearchEvent
from app.schemas.research_event import ResearchEventCreate, ResearchEventUpdate


class ResearchEventRepository:
    """Repository for ResearchEvent operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, tenant_id: UUID, event_id: UUID) -> Optional[ResearchEvent]:
        """Get a research event by ID, scoped to tenant."""
        result = await self.db.execute(
            select(ResearchEvent).where(
                and_(
                    ResearchEvent.id == event_id,
                    ResearchEvent.tenant_id == tenant_id
                )
            )
        )
        return result.scalar_one_or_none()
    
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
    ) -> list[ResearchEvent]:
        """Get research events for a tenant with optional filters."""
        query = select(ResearchEvent).where(ResearchEvent.tenant_id == tenant_id)
        
        if entity_type:
            query = query.where(ResearchEvent.entity_type == entity_type)
        if entity_id:
            query = query.where(ResearchEvent.entity_id == entity_id)
        if source_type:
            query = query.where(ResearchEvent.source_type == source_type)
        if date_from:
            query = query.where(ResearchEvent.created_at >= date_from)
        if date_to:
            query = query.where(ResearchEvent.created_at <= date_to)
        
        query = query.order_by(ResearchEvent.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def create(self, tenant_id: UUID, data: ResearchEventCreate) -> ResearchEvent:
        """Create a new research event."""
        event = ResearchEvent(
            tenant_id=tenant_id,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            source_type=data.source_type,
            source_url=data.source_url,
            raw_payload=data.raw_payload,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event
    
    async def update(self, event: ResearchEvent, data: ResearchEventUpdate) -> ResearchEvent:
        """Update a research event."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(event, field, value)
        
        await self.db.flush()
        await self.db.refresh(event)
        return event
    
    async def delete(self, event: ResearchEvent) -> None:
        """Delete a research event."""
        await self.db.delete(event)
        await self.db.flush()

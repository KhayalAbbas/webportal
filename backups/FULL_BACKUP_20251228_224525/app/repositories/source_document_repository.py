"""
Repository for SourceDocument database operations.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source_document import SourceDocument
from app.models.research_event import ResearchEvent
from app.schemas.source_document import SourceDocumentCreate, SourceDocumentUpdate


class SourceDocumentRepository:
    """Repository for SourceDocument operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, tenant_id: UUID, document_id: UUID) -> Optional[SourceDocument]:
        """Get a source document by ID, scoped to tenant."""
        result = await self.db.execute(
            select(SourceDocument).where(
                and_(
                    SourceDocument.id == document_id,
                    SourceDocument.tenant_id == tenant_id
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def get_by_tenant(
        self,
        tenant_id: UUID,
        research_event_id: Optional[UUID] = None,
        document_type: Optional[str] = None,
        target_entity_type: Optional[str] = None,
        target_entity_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50
    ) -> list[SourceDocument]:
        """Get source documents for a tenant with optional filters."""
        query = select(SourceDocument).where(SourceDocument.tenant_id == tenant_id)
        
        if research_event_id:
            query = query.where(SourceDocument.research_event_id == research_event_id)
        if document_type:
            query = query.where(SourceDocument.document_type == document_type)
        
        # Filter by target entity via ResearchEvent
        if target_entity_type or target_entity_id:
            query = query.join(ResearchEvent, SourceDocument.research_event_id == ResearchEvent.id)
            if target_entity_type:
                query = query.where(ResearchEvent.entity_type == target_entity_type)
            if target_entity_id:
                query = query.where(ResearchEvent.entity_id == target_entity_id)
        
        query = query.order_by(SourceDocument.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_research_event(self, research_event_id: UUID) -> list[SourceDocument]:
        """Get all source documents for a research event."""
        result = await self.db.execute(
            select(SourceDocument)
            .where(SourceDocument.research_event_id == research_event_id)
            .order_by(SourceDocument.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def create(self, tenant_id: UUID, data: SourceDocumentCreate) -> SourceDocument:
        """Create a new source document."""
        document = SourceDocument(
            tenant_id=tenant_id,
            research_event_id=data.research_event_id,
            document_type=data.document_type,
            title=data.title,
            url=data.url,
            storage_path=data.storage_path,
            text_content=data.text_content,
            metadata=data.metadata,
        )
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return document
    
    async def update(self, document: SourceDocument, data: SourceDocumentUpdate) -> SourceDocument:
        """Update a source document."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(document, field, value)
        
        await self.db.flush()
        await self.db.refresh(document)
        return document
    
    async def delete(self, document: SourceDocument) -> None:
        """Delete a source document."""
        await self.db.delete(document)
        await self.db.flush()

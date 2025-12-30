"""
Service layer for SourceDocument business logic.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.source_document_repository import SourceDocumentRepository
from app.repositories.research_event_repository import ResearchEventRepository
from app.schemas.source_document import SourceDocumentCreate, SourceDocumentUpdate, SourceDocumentRead


class SourceDocumentService:
    """Service for SourceDocument business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SourceDocumentRepository(db)
        self.research_event_repository = ResearchEventRepository(db)
    
    async def get_by_id(self, tenant_id: UUID, document_id: UUID) -> Optional[SourceDocumentRead]:
        """Get a source document by ID."""
        document = await self.repository.get_by_id(tenant_id, document_id)
        return SourceDocumentRead.model_validate(document) if document else None
    
    async def get_by_tenant(
        self,
        tenant_id: UUID,
        research_event_id: Optional[UUID] = None,
        document_type: Optional[str] = None,
        target_entity_type: Optional[str] = None,
        target_entity_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 50
    ) -> list[SourceDocumentRead]:
        """Get source documents with filters."""
        documents = await self.repository.get_by_tenant(
            tenant_id=tenant_id,
            research_event_id=research_event_id,
            document_type=document_type,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            skip=skip,
            limit=limit
        )
        return [SourceDocumentRead.model_validate(d) for d in documents]
    
    async def create(self, tenant_id: UUID, data: SourceDocumentCreate) -> Optional[SourceDocumentRead]:
        """Create a new source document."""
        # Verify research event exists and belongs to tenant
        research_event = await self.research_event_repository.get_by_id(
            tenant_id, data.research_event_id
        )
        if not research_event:
            return None
        
        document = await self.repository.create(tenant_id, data)
        await self.db.commit()
        return SourceDocumentRead.model_validate(document)
    
    async def update(
        self,
        tenant_id: UUID,
        document_id: UUID,
        data: SourceDocumentUpdate
    ) -> Optional[SourceDocumentRead]:
        """Update a source document."""
        document = await self.repository.get_by_id(tenant_id, document_id)
        if not document:
            return None
        
        updated_document = await self.repository.update(document, data)
        await self.db.commit()
        return SourceDocumentRead.model_validate(updated_document)
    
    async def delete(self, tenant_id: UUID, document_id: UUID) -> bool:
        """Delete a source document."""
        document = await self.repository.get_by_id(tenant_id, document_id)
        if not document:
            return False
        
        await self.repository.delete(document)
        await self.db.commit()
        return True

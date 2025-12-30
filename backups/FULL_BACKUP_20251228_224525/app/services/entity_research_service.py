"""
Service for retrieving combined research data for entities.
"""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.research_event_repository import ResearchEventRepository
from app.repositories.source_document_repository import SourceDocumentRepository
from app.repositories.ai_enrichment_repository import AIEnrichmentRepository
from app.schemas.research_event import ResearchEventRead
from app.schemas.source_document import SourceDocumentRead
from app.schemas.ai_enrichment import AIEnrichmentRead
from app.schemas.entity_research import EntityResearchData


class EntityResearchService:
    """Service for retrieving all research data for an entity."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.research_event_repo = ResearchEventRepository(db)
        self.source_document_repo = SourceDocumentRepository(db)
        self.ai_enrichment_repo = AIEnrichmentRepository(db)
    
    async def get_entity_research(
        self,
        tenant_id: UUID,
        entity_type: str,
        entity_id: UUID
    ) -> EntityResearchData:
        """
        Get all research data for a specific entity.
        
        Args:
            tenant_id: Tenant UUID
            entity_type: CANDIDATE, COMPANY, or ROLE
            entity_id: Entity UUID
            
        Returns:
            EntityResearchData with research events, source documents, and AI enrichments
        """
        # Get all research events for this entity
        research_events = await self.research_event_repo.get_by_tenant(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            skip=0,
            limit=200  # Get more for convenience endpoints
        )
        
        # Get all source documents linked to these research events
        source_documents = await self.source_document_repo.get_by_tenant(
            tenant_id=tenant_id,
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            skip=0,
            limit=200
        )
        
        # Get all AI enrichments for this entity
        ai_enrichments = await self.ai_enrichment_repo.get_by_target(
            tenant_id=tenant_id,
            target_type=entity_type,
            target_id=entity_id
        )
        
        return EntityResearchData(
            research_events=[ResearchEventRead.model_validate(e) for e in research_events],
            source_documents=[SourceDocumentRead.model_validate(d) for d in source_documents],
            ai_enrichments=[AIEnrichmentRead.model_validate(a) for a in ai_enrichments]
        )

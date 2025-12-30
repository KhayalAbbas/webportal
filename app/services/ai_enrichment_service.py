"""
Service layer for AIEnrichmentRecord business logic.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_enrichment_repository import AIEnrichmentRepository
from app.schemas.ai_enrichment import AIEnrichmentCreate, AIEnrichmentUpdate, AIEnrichmentRead


class AIEnrichmentService:
    """Service for AIEnrichmentRecord business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = AIEnrichmentRepository(db)
    
    async def get_by_id(self, tenant_id: UUID, enrichment_id: UUID) -> Optional[AIEnrichmentRead]:
        """Get an AI enrichment record by ID."""
        enrichment = await self.repository.get_by_id(tenant_id, enrichment_id)
        return AIEnrichmentRead.model_validate(enrichment) if enrichment else None
    
    async def get_by_tenant(
        self,
        tenant_id: UUID,
        target_type: Optional[str] = None,
        target_id: Optional[UUID] = None,
        enrichment_type: Optional[str] = None,
        model_name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50
    ) -> list[AIEnrichmentRead]:
        """Get AI enrichment records with filters."""
        enrichments = await self.repository.get_by_tenant(
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
            enrichment_type=enrichment_type,
            model_name=model_name,
            date_from=date_from,
            date_to=date_to,
            skip=skip,
            limit=limit
        )
        return [AIEnrichmentRead.model_validate(e) for e in enrichments]
    
    async def create(self, tenant_id: UUID, data: AIEnrichmentCreate) -> AIEnrichmentRead:
        """Create a new AI enrichment record."""
        enrichment = await self.repository.create(tenant_id, data)
        await self.db.commit()
        return AIEnrichmentRead.model_validate(enrichment)
    
    async def update(
        self,
        tenant_id: UUID,
        enrichment_id: UUID,
        data: AIEnrichmentUpdate
    ) -> Optional[AIEnrichmentRead]:
        """Update an AI enrichment record."""
        enrichment = await self.repository.get_by_id(tenant_id, enrichment_id)
        if not enrichment:
            return None
        
        updated_enrichment = await self.repository.update(enrichment, data)
        await self.db.commit()
        return AIEnrichmentRead.model_validate(updated_enrichment)
    
    async def delete(self, tenant_id: UUID, enrichment_id: UUID) -> bool:
        """Delete an AI enrichment record."""
        enrichment = await self.repository.get_by_id(tenant_id, enrichment_id)
        if not enrichment:
            return False
        
        await self.repository.delete(enrichment)
        await self.db.commit()
        return True

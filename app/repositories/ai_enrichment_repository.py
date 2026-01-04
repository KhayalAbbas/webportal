"""
Repository for AIEnrichmentRecord database operations.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.schemas.ai_enrichment import AIEnrichmentCreate, AIEnrichmentUpdate


class AIEnrichmentRepository:
    """Repository for AIEnrichmentRecord operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, tenant_id: UUID, enrichment_id: UUID) -> Optional[AIEnrichmentRecord]:
        """Get an AI enrichment record by ID, scoped to tenant."""
        result = await self.db.execute(
            select(AIEnrichmentRecord).where(
                and_(
                    AIEnrichmentRecord.id == enrichment_id,
                    AIEnrichmentRecord.tenant_id == tenant_id
                )
            )
        )
        return result.scalar_one_or_none()
    
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
    ) -> list[AIEnrichmentRecord]:
        """Get AI enrichment records for a tenant with optional filters."""
        query = select(AIEnrichmentRecord).where(AIEnrichmentRecord.tenant_id == tenant_id)
        
        if target_type:
            query = query.where(AIEnrichmentRecord.target_type == target_type)
        if target_id:
            query = query.where(AIEnrichmentRecord.target_id == target_id)
        if enrichment_type:
            query = query.where(AIEnrichmentRecord.enrichment_type == enrichment_type)
        if model_name:
            query = query.where(AIEnrichmentRecord.model_name == model_name)
        if date_from:
            query = query.where(AIEnrichmentRecord.created_at >= date_from)
        if date_to:
            query = query.where(AIEnrichmentRecord.created_at <= date_to)
        
        query = query.order_by(AIEnrichmentRecord.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_target(
        self,
        tenant_id: UUID,
        target_type: str,
        target_id: UUID
    ) -> list[AIEnrichmentRecord]:
        """Get all AI enrichments for a specific target."""
        result = await self.db.execute(
            select(AIEnrichmentRecord)
            .where(
                and_(
                    AIEnrichmentRecord.tenant_id == tenant_id,
                    AIEnrichmentRecord.target_type == target_type,
                    AIEnrichmentRecord.target_id == target_id
                )
            )
            .order_by(AIEnrichmentRecord.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def create(self, tenant_id: UUID, data: AIEnrichmentCreate) -> AIEnrichmentRecord:
        """Create a new AI enrichment record."""
        enrichment = AIEnrichmentRecord(
            tenant_id=tenant_id,
            target_type=data.target_type,
            target_id=data.target_id,
            model_name=data.model_name,
            enrichment_type=data.enrichment_type,
            payload=data.payload,
            company_research_run_id=data.company_research_run_id,
            purpose=data.purpose,
            provider=data.provider,
            input_scope_hash=data.input_scope_hash,
            content_hash=data.content_hash,
            source_document_id=data.source_document_id,
            status=data.status,
            error_message=data.error_message,
        )
        self.db.add(enrichment)
        await self.db.flush()
        await self.db.refresh(enrichment)
        return enrichment
    
    async def update(self, enrichment: AIEnrichmentRecord, data: AIEnrichmentUpdate) -> AIEnrichmentRecord:
        """Update an AI enrichment record."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(enrichment, field, value)
        
        await self.db.flush()
        await self.db.refresh(enrichment)
        return enrichment
    
    async def delete(self, enrichment: AIEnrichmentRecord) -> None:
        """Delete an AI enrichment record."""
        await self.db.delete(enrichment)
        await self.db.flush()

    async def get_by_hash(
        self,
        tenant_id: UUID,
        provider: str,
        purpose: str,
        content_hash: str,
        target_id: UUID,
        target_type: str,
    ) -> Optional[AIEnrichmentRecord]:
        """Return an enrichment by its idempotency key."""
        result = await self.db.execute(
            select(AIEnrichmentRecord).where(
                and_(
                    AIEnrichmentRecord.tenant_id == tenant_id,
                    AIEnrichmentRecord.provider == provider,
                    AIEnrichmentRecord.purpose == purpose,
                    AIEnrichmentRecord.content_hash == content_hash,
                    AIEnrichmentRecord.target_id == target_id,
                    AIEnrichmentRecord.target_type == target_type,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_for_provider(
        self,
        tenant_id: UUID,
        provider: str,
        purpose: str,
        target_id: UUID,
        target_type: str,
    ) -> Optional[AIEnrichmentRecord]:
        """Return the most recent enrichment for a provider and target."""
        result = await self.db.execute(
            select(AIEnrichmentRecord)
            .where(
                and_(
                    AIEnrichmentRecord.tenant_id == tenant_id,
                    AIEnrichmentRecord.provider == provider,
                    AIEnrichmentRecord.purpose == purpose,
                    AIEnrichmentRecord.target_id == target_id,
                    AIEnrichmentRecord.target_type == target_type,
                )
            )
            .order_by(desc(AIEnrichmentRecord.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

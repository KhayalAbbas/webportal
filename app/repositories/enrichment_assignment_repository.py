"""
Repository for enrichment assignment database operations.
"""

import uuid
from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_
from sqlalchemy.dialects.postgresql import insert

from app.models.enrichment_assignment import EnrichmentAssignment
from app.schemas.enrichment_assignment import EnrichmentAssignmentCreate


class EnrichmentAssignmentRepository:
    """CRUD and idempotent upsert helpers for enrichment assignments."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_assignment(
        self,
        tenant_id: str,
        data: EnrichmentAssignmentCreate,
        value_json: dict,
        content_hash: str,
    ) -> EnrichmentAssignment:
        base_insert = insert(EnrichmentAssignment).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            target_entity_type=data.target_entity_type,
            target_canonical_id=data.target_canonical_id,
            field_key=data.field_key,
            value_json=value_json,
            value_normalized=data.value_normalized,
            confidence=data.confidence,
            derived_by=data.derived_by,
            source_document_id=data.source_document_id,
            input_scope_hash=data.input_scope_hash,
            content_hash=content_hash,
        )
        stmt = base_insert.on_conflict_do_update(
            constraint="uq_enrichment_assignment_idempotent",
            set_={
                "value_json": base_insert.excluded.value_json,
                "value_normalized": base_insert.excluded.value_normalized,
                "confidence": base_insert.excluded.confidence,
                "derived_by": base_insert.excluded.derived_by,
                "input_scope_hash": base_insert.excluded.input_scope_hash,
                "updated_at": func.now(),
            },
        ).returning(EnrichmentAssignment)
        result = await self.db.execute(stmt)
        record = result.scalar_one()
        await self.db.flush()
        return record

    async def list_for_target(
        self,
        tenant_id: str,
        target_entity_type: str,
        target_canonical_id: UUID,
    ) -> List[EnrichmentAssignment]:
        query = (
            select(EnrichmentAssignment)
            .where(
                and_(
                    EnrichmentAssignment.tenant_id == tenant_id,
                    EnrichmentAssignment.target_entity_type == target_entity_type,
                    EnrichmentAssignment.target_canonical_id == target_canonical_id,
                )
            )
            .order_by(EnrichmentAssignment.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_for_company_ids(
        self,
        tenant_id: str,
        canonical_ids: List[UUID],
    ) -> List[EnrichmentAssignment]:
        """Batch fetch enrichment assignments for canonical companies."""
        if not canonical_ids:
            return []

        query = (
            select(EnrichmentAssignment)
            .where(
                EnrichmentAssignment.tenant_id == tenant_id,
                EnrichmentAssignment.target_entity_type == "company",
                EnrichmentAssignment.target_canonical_id.in_(canonical_ids),
            )
            .order_by(EnrichmentAssignment.target_canonical_id.asc(), EnrichmentAssignment.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

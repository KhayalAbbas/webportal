"""
Service for enrichment assignments with evidence-backed, idempotent writes.
"""

import hashlib
import json
from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.enrichment_assignment_repository import EnrichmentAssignmentRepository
from app.schemas.enrichment_assignment import EnrichmentAssignmentCreate, EnrichmentAssignmentRead

JsonValue = dict | list | str | int | float | bool | None


class EnrichmentAssignmentService:
    """Service exposing deterministic, evidence-first enrichment assignments."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EnrichmentAssignmentRepository(db)

    def _canonical_value(self, value: JsonValue) -> JsonValue:
        try:
            json.dumps(value, sort_keys=True, default=str)
            return value
        except TypeError:
            return str(value)

    def _compute_content_hash(
        self,
        payload: EnrichmentAssignmentCreate,
        canonical_value: JsonValue,
    ) -> str:
        base = {
            "target_entity_type": payload.target_entity_type,
            "target_canonical_id": str(payload.target_canonical_id),
            "field_key": payload.field_key,
            "value": canonical_value,
            "value_normalized": payload.value_normalized,
            "derived_by": payload.derived_by,
            "source_document_id": str(payload.source_document_id),
            "input_scope_hash": payload.input_scope_hash,
        }
        serialized = json.dumps(base, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def record_assignment(
        self,
        tenant_id: str,
        payload: EnrichmentAssignmentCreate,
    ) -> EnrichmentAssignmentRead:
        if not payload.source_document_id:
            raise ValueError("source_document_required")
        canonical_value = self._canonical_value(payload.value)
        content_hash = self._compute_content_hash(payload, canonical_value)
        record = await self.repo.upsert_assignment(
            tenant_id=tenant_id,
            data=payload,
            value_json=canonical_value,
            content_hash=content_hash,
        )
        await self.db.commit()
        data = record.__dict__.copy()
        data["value"] = record.value_json
        return EnrichmentAssignmentRead.model_validate(data, from_attributes=True)

    async def record_assignments(
        self,
        tenant_id: str,
        payloads: List[EnrichmentAssignmentCreate],
    ) -> List[EnrichmentAssignmentRead]:
        results: List[EnrichmentAssignmentRead] = []
        for payload in payloads:
            results.append(await self.record_assignment(tenant_id, payload))
        return results

    async def list_for_canonical_company(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
    ) -> List[EnrichmentAssignmentRead]:
        records = await self.repo.list_for_target(tenant_id, "company", canonical_company_id)
        return [self._to_read(record) for record in records]

    async def list_for_canonical_person(
        self,
        tenant_id: str,
        canonical_person_id: UUID,
    ) -> List[EnrichmentAssignmentRead]:
        records = await self.repo.list_for_target(tenant_id, "person", canonical_person_id)
        return [self._to_read(record) for record in records]

    def _to_read(self, record) -> EnrichmentAssignmentRead:
        data = record.__dict__.copy()
        data["value"] = record.value_json
        return EnrichmentAssignmentRead.model_validate(data, from_attributes=True)

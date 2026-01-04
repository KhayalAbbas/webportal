"""
Repository for CandidateContactPoint database operations.
"""

from typing import List, Tuple
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_contact_point import CandidateContactPoint


class CandidateContactPointRepository:
    """Repository for candidate contact points."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_candidate(self, tenant_id: UUID | str, candidate_id: UUID) -> List[CandidateContactPoint]:
        """Return contact points for a candidate ordered by newest."""
        result = await self.db.execute(
            select(CandidateContactPoint)
            .where(
                and_(
                    CandidateContactPoint.tenant_id == tenant_id,
                    CandidateContactPoint.candidate_id == candidate_id,
                )
            )
            .order_by(CandidateContactPoint.updated_at.desc())
        )
        return list(result.scalars().all())

    async def upsert_points(
        self,
        tenant_id: UUID | str,
        candidate_id: UUID,
        points: List[dict],
    ) -> Tuple[List[CandidateContactPoint], List[CandidateContactPoint]]:
        """Insert or update contact points; returns (added, existing)."""
        added: List[CandidateContactPoint] = []
        existing: List[CandidateContactPoint] = []

        for point in points:
            query = select(CandidateContactPoint).where(
                and_(
                    CandidateContactPoint.tenant_id == tenant_id,
                    CandidateContactPoint.candidate_id == candidate_id,
                    CandidateContactPoint.kind == point["kind"],
                    CandidateContactPoint.value_normalized == point["value_normalized"],
                )
            )
            result = await self.db.execute(query)
            current = result.scalar_one_or_none()

            if current:
                # Update minimal fields if we learned more
                current.value_raw = point["value_raw"]
                if point.get("label"):
                    current.label = point["label"]
                if point.get("provider"):
                    current.provider = point["provider"]
                if point.get("confidence") is not None:
                    current.confidence = point["confidence"]
                if point.get("source_document_id"):
                    current.source_document_id = point["source_document_id"]
                if point.get("is_primary"):
                    current.is_primary = point["is_primary"]
                await self.db.flush()
                await self.db.refresh(current)
                existing.append(current)
                continue

            record = CandidateContactPoint(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                kind=point["kind"],
                value_raw=point["value_raw"],
                value_normalized=point["value_normalized"],
                label=point.get("label"),
                is_primary=bool(point.get("is_primary", False)),
                provider=point.get("provider"),
                confidence=point.get("confidence"),
                source_document_id=point.get("source_document_id"),
            )
            self.db.add(record)
            await self.db.flush()
            await self.db.refresh(record)
            added.append(record)

        return added, existing

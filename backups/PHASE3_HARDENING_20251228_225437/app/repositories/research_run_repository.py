"""
Repository for Phase 3 research run ledger.
"""

from typing import Dict, Optional, List
from uuid import UUID
import uuid

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_run import ResearchRun, ResearchRunStep


class ResearchRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, tenant_id: UUID, run_id: UUID) -> Optional[ResearchRun]:
        result = await self.db.execute(
            select(ResearchRun).where(
                ResearchRun.id == run_id,
                ResearchRun.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, tenant_id: UUID, key: str) -> Optional[ResearchRun]:
        result = await self.db.execute(
            select(ResearchRun).where(
                ResearchRun.tenant_id == tenant_id,
                ResearchRun.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def create_run(
        self,
        tenant_id: UUID,
        data: dict,
        created_by_user_id: Optional[UUID] = None,
    ) -> ResearchRun:
        run = ResearchRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_by_user_id=created_by_user_id,
            **data,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def upsert_steps(
        self,
        tenant_id: UUID,
        run_id: UUID,
        steps: List[dict],
    ) -> List[ResearchRunStep]:
        persisted: List[ResearchRunStep] = []
        for payload in steps:
            existing = await self.db.execute(
                select(ResearchRunStep).where(
                    ResearchRunStep.tenant_id == tenant_id,
                    ResearchRunStep.run_id == run_id,
                    ResearchRunStep.step_key == payload["step_key"],
                )
            )
            step = existing.scalar_one_or_none()
            if not step:
                step = ResearchRunStep(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    run_id=run_id,
                    **payload,
                )
                self.db.add(step)
            else:
                # Update mutable fields for idempotent overwrite
                step.status = payload.get("status", step.status)
                step.step_type = payload.get("step_type", step.step_type)
                step.inputs_json = payload.get("inputs_json", step.inputs_json)
                step.outputs_json = payload.get("outputs_json", step.outputs_json)
                step.provider_meta = payload.get("provider_meta", step.provider_meta)
                step.started_at = payload.get("started_at", step.started_at)
                step.finished_at = payload.get("finished_at", step.finished_at)
                step.output_sha256 = payload.get("output_sha256", step.output_sha256)
                step.error = payload.get("error", step.error)
            persisted.append(step)
        await self.db.flush()
        return persisted

    async def list_steps(self, tenant_id: UUID, run_id: UUID) -> List[ResearchRunStep]:
        result = await self.db.execute(
            select(ResearchRunStep)
            .where(
                ResearchRunStep.tenant_id == tenant_id,
                ResearchRunStep.run_id == run_id,
            )
            .order_by(ResearchRunStep.created_at)
        )
        return list(result.scalars().all())

    async def count_steps_by_status(self, tenant_id: UUID, run_id: UUID) -> Dict[str, int]:
        result = await self.db.execute(
            select(ResearchRunStep.status, func.count())
            .where(
                ResearchRunStep.tenant_id == tenant_id,
                ResearchRunStep.run_id == run_id,
            )
            .group_by(ResearchRunStep.status)
        )
        rows = result.all()
        return {row[0]: row[1] for row in rows}

"""
Phase 3: Research run ledger and bundle upload endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.research_run import (
    ResearchRunCreate,
    ResearchRunRead,
    ResearchRunWithCounts,
    ResearchRunStepRead,
    RunBundleV1,
    BundleAcceptedResponse,
)
from app.services.research_run_service import ResearchRunService

router = APIRouter(prefix="/api/runs", tags=["Research Runs"])


@router.post("/", response_model=ResearchRunRead, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: ResearchRunCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = ResearchRunService(db)
    run = await service.create_run(current_user.tenant_id, payload, current_user.id)
    await db.commit()
    return ResearchRunRead.model_validate(run)


@router.get("/{run_id}", response_model=ResearchRunWithCounts)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = ResearchRunService(db)
    run = await service.get_run_with_counts(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}/steps", response_model=list[ResearchRunStepRead])
async def list_steps(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = ResearchRunService(db)
    steps = await service.list_steps(current_user.tenant_id, run_id)
    return [ResearchRunStepRead.model_validate(s) for s in steps]


@router.post("/{run_id}/bundle", response_model=BundleAcceptedResponse)
async def upload_bundle(
    run_id: UUID,
    payload: RunBundleV1,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = ResearchRunService(db)
    try:
        response, ingested = await service.accept_bundle(current_user.tenant_id, run_id, payload)
        return response
    except ValueError as exc:
        msg = str(exc)
        if msg == "run_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if msg == "bundle_run_id_mismatch":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bundle run_id mismatch")
        if msg.startswith("company_missing_evidence"):
            name = msg.split(":", 1)[1] if ":" in msg else "unknown"
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Company '{name}' missing evidence")
        if msg.startswith("company_missing_evidence_snippets"):
            name = msg.split(":", 1)[1] if ":" in msg else "unknown"
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Company '{name}' missing evidence snippets")
        if msg.startswith("company_missing_source_sha256s"):
            name = msg.split(":", 1)[1] if ":" in msg else "unknown"
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Company '{name}' missing source SHA256 references")
        if msg.startswith("company_references_unknown_source"):
            parts = msg.split(":", 2)
            name, sha256 = (parts[1], parts[2]) if len(parts) == 3 else ("unknown", "unknown")
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Company '{name}' references unknown source: {sha256}")
        if msg.startswith("ingestion_failed"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
        # Generic validation error payload (JSON string)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)
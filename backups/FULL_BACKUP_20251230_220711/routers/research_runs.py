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
    accept_only: bool = False,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a research bundle for a run.
    
    Args:
        run_id: The research run ID
        payload: The bundle data
        accept_only: If True, only accept the bundle for review (don't start ingestion)
        current_user: Authenticated user
        db: Database session
        
    Returns:
        BundleAcceptedResponse with status and processing information
    """
    service = ResearchRunService(db)
    try:
        response, ingested = await service.accept_bundle(
            current_user.tenant_id, 
            run_id, 
            payload,
            accept_only=accept_only
        )
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
        if msg.startswith("bundle_validation_failed"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.post("/{run_id}/approve", response_model=dict)
async def approve_bundle_for_ingestion(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a bundle that's in needs_review status for background ingestion.
    
    Args:
        run_id: The research run ID
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Dict with job_id and status information
    """
    service = ResearchRunService(db)
    try:
        result = await service.approve_bundle_for_ingestion(current_user.tenant_id, run_id)
        return result
    except ValueError as exc:
        msg = str(exc)
        if msg == "run_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if msg.startswith("run_status_not_reviewable"):
            status_detail = msg.split(":", 1)[1] if ":" in msg else "unknown"
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                                detail=f"Run not in reviewable status: {status_detail}")
        if msg == "run_missing_bundle":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Run missing bundle")
        if msg == "stored_bundle_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored bundle not found")
        if msg.startswith("bundle_parse_error"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.get("/{run_id}/bundle", response_model=dict)
async def download_bundle(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the stored bundle JSON for a research run.
    
    Args:
        run_id: The research run ID
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Dict containing the bundle JSON data
    """
    service = ResearchRunService(db)
    try:
        stored_bundle = await service._get_stored_bundle(current_user.tenant_id, run_id)
        if not stored_bundle:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")
        
        return {
            "run_id": str(run_id),
            "bundle_sha256": stored_bundle.bundle_sha256,
            "created_at": stored_bundle.created_at.isoformat(),
            "bundle_json": stored_bundle.bundle_json
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
        if msg.startswith("ingestion_failed"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
        # Generic validation error payload (JSON string)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)
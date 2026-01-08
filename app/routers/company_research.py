"""
Company Research Router - API endpoints.

Provides REST API for company discovery and agentic sourcing.
Phase 1: Backend structures, no external AI orchestration yet.
"""

import base64
import binascii
import csv
import hashlib
import io
import os
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_db, verify_user_tenant_access
from app.errors import raise_app_error
from app.models.user import User
from app.services.company_research_service import CompanyResearchService
from app.services.contact_enrichment_service import ContactEnrichmentService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyResearchRunRead,
    CompanyResearchRunUpdate,
    CompanyResearchRunSummary,
    CompanyResearchJobRead,
    CompanyResearchRunPlanRead,
    CompanyResearchRunStepRead,
    CompanyProspectCreate,
    CompanyProspectRead,
    CompanyProspectListItem,
    CompanyProspectWithEvidence,
    CompanyProspectRanking,
    ExecutiveRanking,
    ExecutiveProspectRead,
    ExecutivePipelineCreate,
    ExecutivePipelineCreateResponse,
    ExecutiveCompareResponse,
    ExecutiveMergeDecisionRequest,
    ExecutiveMergeDecisionRead,
    CompanyProspectUpdateManual,
    CompanyProspectReviewUpdate,
    ExecutiveVerificationUpdate,
    ExecutiveReviewUpdate,
    CompanyProspectEvidenceCreate,
    CompanyProspectEvidenceRead,
    CompanyProspectMetricCreate,
    CompanyProspectMetricRead,
    ResearchEventRead,
    SourceDocumentRead,
    SourceDocumentCreate,
    ResolvedEntityRead,
    EntityMergeLinkRead,
    CanonicalPersonRead,
    CanonicalPersonListItem,
    CanonicalPersonLinkRead,
    CanonicalCompanyRead,
    CanonicalCompanyListItem,
    CanonicalCompanyLinkRead,
    DiscoveryProviderRunPayload,
    DiscoveryProviderRunResponse,
    ExternalLLMDiscoveryIngestRequest,
    ExternalLLMDiscoveryIngestResponse,
    RunPack,
    ExecutiveDiscoveryRunResponse,
    MarketTestRequest,
    MarketTestResponse,
    AcquireExtractRequest,
    AcquireExtractResponse,
    AcquireExtractJobEnqueueResponse,
    AcquireExtractJobStatusResponse,
    AcquireExtractLeaseRecoveryRequest,
    AcquireExtractLeaseRecoveryResponse,
    ExportPackRead,
)
from app.schemas.contact_enrichment import ContactEnrichmentRequest
from app.schemas.executive_contact_enrichment import (
    ExecutiveContactEnrichmentResponse,
    BulkExecutiveContactEnrichmentRequest,
    BulkExecutiveContactEnrichmentResponse,
    BulkExecutiveContactEnrichmentResponseItem,
)
from app.schemas.executive_discovery import ExecutiveDiscoveryPayload


def _apply_rank_filters(
    items: List[CompanyProspectRanking],
    min_score: Optional[float] = None,
    has_hq: bool = False,
    has_ownership: bool = False,
    has_industry: bool = False,
    review_status: Optional[str] = None,
    verification_status: Optional[str] = None,
    discovered_by: Optional[str] = None,
    exec_search_enabled: Optional[bool] = None,
) -> List[CompanyProspectRanking]:
    """Filter ranked prospects without altering ordering."""

    def _has_signal(signals, key: str) -> bool:
        return any(getattr(sig, "field_key", None) == key for sig in signals)

    filtered: List[CompanyProspectRanking] = []
    for item in items:
        signals = list(item.why_included or [])
        if min_score is not None and float(item.computed_score) < float(min_score):
            continue
        if has_hq and not item.hq_country:
            continue
        if has_ownership and not _has_signal(signals, "ownership_signal"):
            continue
        if has_industry and not _has_signal(signals, "industry_keywords"):
            continue
        if review_status and getattr(item, "review_status", None) != review_status:
            continue
        if verification_status and getattr(item, "verification_status", None) != verification_status:
            continue
        if discovered_by and getattr(item, "discovered_by", None) != discovered_by:
            continue
        if exec_search_enabled is not None and getattr(item, "exec_search_enabled", None) != exec_search_enabled:
            continue
        filtered.append(item)

    return filtered


async def _get_filtered_rankings(
    service: CompanyResearchService,
    tenant_id: str,
    run_id: UUID,
    status: Optional[str],
    min_relevance_score: Optional[float],
    limit: int,
    offset: int,
    min_score: Optional[float],
    has_hq: bool,
    has_ownership: bool,
    has_industry: bool,
    review_status: Optional[str],
    verification_status: Optional[str],
    discovered_by: Optional[str],
    exec_search_enabled: Optional[bool],
) -> List[CompanyProspectRanking]:
    run = await service.get_research_run(tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    ranked_raw = await service.rank_prospects_for_run(
        tenant_id=tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        limit=limit,
        offset=offset,
    )

    ranked = [CompanyProspectRanking.model_validate(item) for item in ranked_raw]
    return _apply_rank_filters(
        ranked,
        min_score,
        has_hq,
        has_ownership,
        has_industry,
        review_status,
        verification_status,
        discovered_by,
        exec_search_enabled,
    )


async def _get_ranked_executives(
    service: CompanyResearchService,
    tenant_id: str,
    run_id: UUID,
    *,
    company_prospect_id: Optional[UUID],
    provenance: Optional[str],
    verification_status: Optional[str],
    q: Optional[str],
    limit: int,
    offset: int,
) -> List[ExecutiveRanking]:
    run = await service.get_research_run(tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    ranked_raw = await service.rank_executives_for_run(
        tenant_id=tenant_id,
        run_id=run_id,
        company_prospect_id=company_prospect_id,
        provenance=provenance,
        verification_status=verification_status,
        q=q,
        limit=limit,
        offset=offset,
    )

    return [ExecutiveRanking.model_validate(item) for item in ranked_raw]

router = APIRouter(prefix="/company-research", tags=["company-research"])


class ManualListSourcePayload(BaseModel):
    title: Optional[str] = None
    content_text: str


class ProposalSourcePayload(BaseModel):
    title: Optional[str] = None
    content_text: str


class UrlSourcePayload(BaseModel):
    title: Optional[str] = None
    url: str
    headers: Optional[dict[str, str]] = None
    timeout_seconds: Optional[int] = Field(default=30, ge=1, le=120)


class PdfSourcePayload(BaseModel):
    title: Optional[str] = None
    file_name: Optional[str] = None
    content_base64: str
    mime_type: Optional[str] = Field(default="application/pdf", max_length=100)


class LlmJsonSourcePayload(BaseModel):
    title: Optional[str] = None
    provider: str
    model: Optional[str] = None
    purpose: str = Field(default="company_discovery")
    payload: dict


class ExecutiveDiscoveryRunPayload(BaseModel):
    mode: str = Field(default="internal", pattern=r"^(internal|external|both)$")
    engine: Optional[str] = Field(default="external", pattern=r"^(internal|external)$")
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    payload: Optional[dict] = None
    external_fixture: Optional[bool] = Field(
        default=False,
        description="Proof-only flag to run deterministic external fixture payload when RUN_PROOFS_FIXTURES=1.",
    )


class ExecutiveEligibilityItem(BaseModel):
    id: UUID
    name_normalized: str
    review_status: str
    exec_search_enabled: bool


# ============================================================================
# Research Run Endpoints
# ============================================================================


@router.get("/runs", response_model=List[CompanyResearchRunRead])
async def list_research_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List research runs for the tenant."""
    service = CompanyResearchService(db)
    runs = await service.list_research_runs(
        tenant_id=current_user.tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [CompanyResearchRunRead.model_validate(r) for r in runs]

@router.post("/runs", response_model=CompanyResearchRunRead)
async def create_research_run(
    data: CompanyResearchRunCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new company research run for a specific role/mandate.
    
    This initializes a discovery exercise with optional ranking and enrichment config.
    """
    service = CompanyResearchService(db)
    
    run = await service.create_research_run(
        tenant_id=current_user.tenant_id,
        data=data,
        created_by_user_id=current_user.id,
    )
    
    await db.commit()
    return CompanyResearchRunRead.model_validate(run)


@router.get("/runs/{run_id}", response_model=CompanyResearchRunSummary)
async def get_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a research run by ID with prospect count summary.
    """
    service = CompanyResearchService(db)
    
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospect_count = await service.count_prospects_for_run(current_user.tenant_id, run_id)
    
    # Build summary response
    run_dict = {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "role_mandate_id": run.role_mandate_id,
        "name": run.name,
        "description": run.description,
        "status": run.status,
        "sector": run.sector,
        "region_scope": getattr(run, "region_scope", None),
        "config": run.config,
        "summary": getattr(run, "summary", None),
        "last_error": getattr(run, "last_error", None),
        "created_by_user_id": run.created_by_user_id,
        "started_at": getattr(run, "started_at", None),
        "finished_at": getattr(run, "finished_at", None),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "prospect_count": prospect_count,
    }
    
    return CompanyResearchRunSummary(**run_dict)


@router.get("/runs/{run_id}/plan", response_model=CompanyResearchRunPlanRead)
async def get_research_run_plan(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Get or build the deterministic plan for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    plan, _ = await service.ensure_plan_and_steps(current_user.tenant_id, run_id)
    return CompanyResearchRunPlanRead.model_validate(plan)


@router.get("/runs/{run_id}/steps", response_model=List[CompanyResearchRunStepRead])
async def list_research_run_steps(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List deterministic steps for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    _, steps = await service.ensure_plan_and_steps(current_user.tenant_id, run_id)
    return [CompanyResearchRunStepRead.model_validate(s) for s in steps]


@router.post("/runs/{run_id}/start", response_model=CompanyResearchJobRead)
async def start_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue a research run for processing."""
    service = CompanyResearchService(db)
    try:
        job = await service.start_run(current_user.tenant_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Research run not found")
    await db.commit()
    return CompanyResearchJobRead.model_validate(job)


@router.post(
    "/runs/{run_id}/acquire-extract",
    response_model=AcquireExtractResponse,
)
async def acquire_and_extract_run(
    run_id: UUID,
    payload: Optional[AcquireExtractRequest] = None,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Synchronously acquire (fetch) and extract sources for a run."""

    service = CompanyResearchService(db)

    try:
        summary = await service.run_acquire_extract(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            max_urls=(payload.max_urls if payload else None),
            force=(payload.force if payload else False),
        )
    except ValueError as exc:  # noqa: BLE001
        if str(exc) == "run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        raise

    await db.commit()
    return AcquireExtractResponse.model_validate(summary)


@router.post(
    "/runs/{run_id}/acquire-extract:enqueue",
    response_model=AcquireExtractJobEnqueueResponse,
)
async def enqueue_acquire_and_extract_run(
    run_id: UUID,
    payload: Optional[AcquireExtractRequest] = None,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue async acquire+extract job for a run."""

    service = CompanyResearchService(db)
    try:
        result = await service.enqueue_acquire_extract_job(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            max_urls=(payload.max_urls if payload else None),
            force=(payload.force if payload else False),
        )
    except ValueError as exc:  # noqa: BLE001
        if str(exc) == "run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        raise

    await db.commit()
    job = result["job"]
    return AcquireExtractJobEnqueueResponse(
        job_id=job.id,
        run_id=job.run_id,
        status=job.status,
        params_hash=result["params_hash"],
        reused_reason=result.get("reused_reason"),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=AcquireExtractJobStatusResponse,
)
async def get_company_research_job(
    job_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Fetch async job status for company research operations."""

    service = CompanyResearchService(db)
    job = await service.get_job_for_tenant(current_user.tenant_id, job_id)
    if not job or job.job_type != "acquire_extract_async":
        raise_app_error(404, "JOB_NOT_FOUND", "Job not found", {"job_id": str(job_id)})

    return AcquireExtractJobStatusResponse(
        job_id=job.id,
        run_id=job.run_id,
        status=job.status,
        params_hash=job.params_hash,
        params_json=job.params_json or {},
        progress_json=job.progress_json or {},
        error_json=job.error_json,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/jobs/{job_id}:cancel",
    response_model=AcquireExtractJobStatusResponse,
)
async def cancel_acquire_extract_job(
    job_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Request cancellation for an acquire+extract job."""

    service = CompanyResearchService(db)
    try:
        job = await service.cancel_acquire_extract_job(current_user.tenant_id, job_id)
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "job_not_found":
            raise_app_error(404, "JOB_NOT_FOUND", "Job not found", {"job_id": str(job_id)})
        if msg == "job_terminal":
            raise_app_error(409, "JOB_NOT_CANCELLABLE", "Job already completed", {"job_id": str(job_id)})
        raise

    await db.commit()
    return AcquireExtractJobStatusResponse(
        job_id=job.id,
        run_id=job.run_id,
        status=job.status,
        params_hash=job.params_hash,
        params_json=job.params_json or {},
        progress_json=job.progress_json or {},
        error_json=job.error_json,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/jobs/{job_id}:retry",
    response_model=AcquireExtractJobStatusResponse,
)
async def retry_acquire_extract_job(
    job_id: UUID,
    reset_attempts: bool = Query(False),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Retry an acquire+extract job from a terminal state."""

    service = CompanyResearchService(db)
    try:
        job = await service.retry_acquire_extract_job(current_user.tenant_id, job_id, reset_attempts=reset_attempts)
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "job_not_found":
            raise_app_error(404, "JOB_NOT_FOUND", "Job not found", {"job_id": str(job_id)})
        if msg == "job_active":
            raise_app_error(409, "JOB_ACTIVE", "Job is already queued or running", {"job_id": str(job_id)})
        raise

    await db.commit()
    return AcquireExtractJobStatusResponse(
        job_id=job.id,
        run_id=job.run_id,
        status=job.status,
        params_hash=job.params_hash,
        params_json=job.params_json or {},
        progress_json=job.progress_json or {},
        error_json=job.error_json,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/jobs/acquire-extract:recover-leases",
    response_model=AcquireExtractLeaseRecoveryResponse,
)
async def recover_acquire_extract_leases(
    payload: AcquireExtractLeaseRecoveryRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Recover stale running acquire+extract jobs by clearing expired leases."""

    service = CompanyResearchService(db)
    jobs = await service.recover_acquire_extract_leases(
        tenant_id=current_user.tenant_id,
        stale_after_seconds=payload.stale_after_seconds,
        limit=payload.limit,
    )
    await db.commit()

    return AcquireExtractLeaseRecoveryResponse(
        recovered_job_ids=[job.id for job in jobs],
        recovered_count=len(jobs),
        stale_after_seconds=payload.stale_after_seconds,
    )


@router.get("/runs/{run_id}/sources", response_model=List[SourceDocumentRead])
async def list_run_sources(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List source documents attached to a run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    docs = await service.list_sources_for_run(current_user.tenant_id, run_id)
    return [SourceDocumentRead.model_validate(doc) for doc in docs]


@router.post("/runs/{run_id}/sources/list", response_model=SourceDocumentRead)
async def add_manual_list_source(
    run_id: UUID,
    payload: ManualListSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach a manual list source document to a run."""
    service = CompanyResearchService(db)
    try:
        await service.ensure_sources_unlocked(current_user.tenant_id, run_id)
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        raise HTTPException(status_code=409, detail="Sources are locked after run start")

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="manual_list",
            title=payload.title or "Manual List",
            content_text=payload.content_text,
            meta={"kind": "list", "source_name": payload.title or "manual_list", "submitted_via": "api"},
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/sources/url", response_model=SourceDocumentRead)
async def add_url_source(
    run_id: UUID,
    payload: UrlSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach a URL source document to a run for fetching."""
    service = CompanyResearchService(db)
    try:
        await service.ensure_sources_unlocked(current_user.tenant_id, run_id)
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        raise HTTPException(status_code=409, detail="Sources are locked after run start")

    meta = {
        "kind": "url",
        "submitted_via": "api",
        "fetch_options": {
            "headers": payload.headers,
            "timeout_seconds": payload.timeout_seconds,
        },
    }

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="url",
            title=payload.title or payload.url,
            url=payload.url,
            meta=meta,
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/sources/pdf", response_model=SourceDocumentRead)
async def add_pdf_source(
    run_id: UUID,
    payload: PdfSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach a PDF source document to a run for extraction."""
    service = CompanyResearchService(db)
    try:
        await service.ensure_sources_unlocked(current_user.tenant_id, run_id)
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        raise HTTPException(status_code=409, detail="Sources are locked after run start")

    try:
        pdf_bytes = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 PDF content")

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF content")

    file_name = payload.file_name or payload.title or "uploaded.pdf"
    url_label = f"uploaded://{file_name}"

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="pdf",
            title=payload.title or file_name,
            file_name=file_name,
            url=url_label,
            mime_type=payload.mime_type,
            content_bytes=pdf_bytes,
            content_size=len(pdf_bytes),
            meta={"kind": "pdf", "submitted_via": "api", "file_name": file_name},
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/sources/proposal", response_model=SourceDocumentRead)
async def add_proposal_source(
    run_id: UUID,
    payload: ProposalSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach an AI proposal JSON payload as a source document for ingestion."""
    service = CompanyResearchService(db)
    try:
        await service.ensure_sources_unlocked(current_user.tenant_id, run_id)
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        raise HTTPException(status_code=409, detail="Sources are locked after run start")

    doc = await service.add_source(
        current_user.tenant_id,
        SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="ai_proposal",
            title=payload.title or "AI Proposal",
            content_text=payload.content_text,
            meta={"kind": "proposal", "submitted_via": "api"},
        ),
    )
    await db.commit()
    return SourceDocumentRead.model_validate(doc)


@router.post("/runs/{run_id}/sources/llm-json")
async def add_llm_json_source(
    run_id: UUID,
    payload: LlmJsonSourcePayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach and ingest an external LLM company discovery JSON payload."""

    service = CompanyResearchService(db)
    try:
        await service.ensure_sources_unlocked(current_user.tenant_id, run_id)
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        raise HTTPException(status_code=409, detail="Sources are locked after run start")

    if payload.purpose != "company_discovery":
        raise HTTPException(status_code=400, detail="purpose must be company_discovery")

    summary = await service.ingest_llm_json_payload(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        payload=payload.payload,
        provider=payload.provider,
        model_name=payload.model,
        title=payload.title,
        purpose=payload.purpose,
    )
    await db.commit()
    return summary


@router.post(
    "/runs/{run_id}/discovery/external-llm/ingest",
    response_model=ExternalLLMDiscoveryIngestResponse,
)
async def ingest_external_llm_discovery(
    run_id: UUID,
    payload: ExternalLLMDiscoveryIngestRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Ingest an external LLM (Grok-style) discovery payload idempotently."""

    service = CompanyResearchService(db)
    try:
        result = await service.ingest_external_llm_discovery(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            request=payload,
            purpose="company_discovery",
        )
    except ValueError as exc:  # noqa: BLE001
        message = str(exc)
        if message == "run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        if message in {"plan_locked", "run_locked"}:
            raise_app_error(409, "SOURCES_LOCKED", "Sources are locked after run start", {"run_id": str(run_id)})
        if message == "invalid_purpose":
            raise_app_error(400, "INVALID_PURPOSE", "purpose must be company_discovery")
        raise

    await db.commit()
    return ExternalLLMDiscoveryIngestResponse.model_validate(result)


@router.post(
    "/runs/{run_id}/discovery/providers/{provider_key}/run",
    response_model=DiscoveryProviderRunResponse,
)
async def run_discovery_provider(
    run_id: UUID,
    provider_key: str,
    payload: DiscoveryProviderRunPayload | None = None,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Run a registered discovery provider and ingest results idempotently."""

    service = CompanyResearchService(db)
    try:
        result = await service.run_discovery_provider(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            provider_key=provider_key,
            request_payload=(payload or DiscoveryProviderRunPayload()).request,
        )
    except ValueError as exc:  # noqa: BLE001
        message = str(exc)
        if message == "invalid_purpose":
            raise HTTPException(status_code=400, detail=message)
        if message == "unknown_provider":
            raise HTTPException(status_code=400, detail="unknown_provider")
        if message == "run_not_found":
            raise HTTPException(status_code=404, detail="Research run not found")
        if message in {"plan_locked", "run_locked"}:
            raise HTTPException(status_code=409, detail="Sources are locked after run start")
        raise

    await db.commit()
    return DiscoveryProviderRunResponse.model_validate(result)


@router.get(
    "/runs/{run_id}/executive-discovery/eligible",
    response_model=List[ExecutiveEligibilityItem],
)
async def list_executive_discovery_eligible(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List companies approved for executive discovery (accepted + exec_search_enabled)."""

    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    eligible = await service.list_executive_eligible_companies(current_user.tenant_id, run_id)
    return [
        ExecutiveEligibilityItem(
            id=prospect.id,
            name_normalized=prospect.name_normalized,
            review_status=prospect.review_status,
            exec_search_enabled=prospect.exec_search_enabled,
        )
        for prospect in eligible
    ]


@router.post(
    "/runs/{run_id}/executive-discovery/run",
    response_model=ExecutiveDiscoveryRunResponse,
)
async def run_executive_discovery(
    run_id: UUID,
    payload: ExecutiveDiscoveryRunPayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Start executive discovery for a run with eligible-first gating and dual-engine orchestration."""

    service = CompanyResearchService(db)

    def http_error(code: str, message: str, status_code: int = 400) -> None:
        raise HTTPException(status_code=status_code, detail={"error": {"code": code, "message": message}})

    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        http_error("run_not_found", "Research run not found", 404)

    if payload.mode not in {"internal", "external", "both"}:
        http_error("invalid_mode", "Invalid mode", 400)

    eligible_companies = await service.list_executive_eligible_companies(current_user.tenant_id, run_id)
    eligible_company_count = len(eligible_companies)
    eligible_norms = {
        service._normalize_company_name(p.name_normalized or p.name_raw) for p in eligible_companies  # noqa: SLF001
    }

    def empty_response(reason: str) -> dict:
        return {
            "run_id": run_id,
            "tenant_id": str(current_user.tenant_id),
            "mode": payload.mode,
            "eligible_company_count": 0,
            "internal": {
                "ran": False,
                "skipped_reason": reason,
                "enrichment_record_id": None,
                "source_document_ids": [],
                "execs_added": 0,
                "execs_updated": 0,
                "eligible_company_count": 0,
                "processed_company_count": 0,
            },
            "external": {
                "ran": False,
                "skipped_reason": reason,
                "enrichment_record_id": None,
                "source_document_ids": [],
                "execs_added": 0,
                "execs_updated": 0,
                "eligible_company_count": 0,
                "processed_company_count": 0,
            },
            "combined": {
                "total_execs_added": 0,
                "total_execs_updated": 0,
            },
            "compare": {
                "matched_count": 0,
                "internal_only_count": 0,
                "external_only_count": 0,
            },
        }

    if eligible_company_count == 0:
        return empty_response("no_eligible_companies")

    external_payload = payload.payload
    external_fixture_requested = bool(payload.external_fixture)

    if payload.mode in {"external", "both"}:
        if not payload.provider and not external_fixture_requested:
            http_error("missing_provider", "provider is required for external mode", 400)
        if not external_payload and not external_fixture_requested:
            http_error("missing_payload", "Missing payload for external mode", 400)

        if external_fixture_requested:
            if os.getenv("RUN_PROOFS_FIXTURES", "0") != "1":
                http_error(
                    "fixture_not_enabled",
                    "external_fixture allowed only when RUN_PROOFS_FIXTURES=1",
                    400,
                )
            external_payload = service.build_external_fixture_payload(eligible_companies)
        else:
            try:
                parsed_payload = ExecutiveDiscoveryPayload(**external_payload)
            except Exception as exc:  # noqa: BLE001
                http_error("invalid_external_payload", str(exc), 400)

            requested_norms: list[str] = []
            for company in parsed_payload.companies:
                norm = service._normalize_company_name(  # noqa: SLF001
                    company.company_normalized or company.company_name
                )
                if norm:
                    requested_norms.append(norm)

            if not requested_norms:
                http_error("no_companies_in_payload", "External payload contained no companies", 400)

            missing = sorted({norm for norm in requested_norms if norm not in eligible_norms})
            if missing:
                http_error("ineligible_companies", ",".join(missing), 400)

    internal_result = None
    external_result = None

    if payload.mode in {"internal", "both"}:
        internal_result = await service.run_internal_executive_discovery(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
        )

    if payload.mode in {"external", "both"}:
        engine = payload.engine or "external"
        try:
            external_result = await service.ingest_executive_llm_json_payload(
                tenant_id=current_user.tenant_id,
                run_id=run_id,
                payload=external_payload,
                provider=payload.provider or "external_fixture",
                model_name=payload.model,
                title=payload.title,
                engine=engine,
                request_payload=external_payload,
            )
        except ValueError as exc:  # noqa: BLE001
            message = str(exc)
            status_code = 400
            if message == "run_not_found":
                status_code = 404
            http_error(message, message, status_code)

    await db.commit()

    compare_counts = await service.compute_exec_engine_compare_counts(current_user.tenant_id, run_id)

    def map_engine(result: Optional[dict]) -> dict:
        if not result:
            return {
                "ran": False,
                "skipped_reason": None,
                "enrichment_record_id": None,
                "source_document_ids": [],
                "execs_added": 0,
                "execs_updated": 0,
                "eligible_company_count": eligible_company_count,
                "processed_company_count": 0,
            }

        skipped = bool(result.get("skipped"))
        execs_added = int(result.get("executives_new", 0))
        execs_updated = int(result.get("executives_existing", 0))
        source_ids: list[str] = []
        for key in ["source_id", "request_source_id"]:
            value = result.get(key)
            if value:
                source_ids.append(str(value))

        return {
            "ran": not skipped,
            "skipped_reason": result.get("reason") if skipped else None,
            "enrichment_record_id": result.get("enrichment_id"),
            "source_document_ids": source_ids,
            "execs_added": execs_added,
            "execs_updated": execs_updated,
            "eligible_company_count": int(result.get("eligible_company_count", eligible_company_count)),
            "processed_company_count": int(result.get("processed_company_count", 0)),
        }

    internal_block = map_engine(internal_result)
    external_block = map_engine(external_result)

    combined = {
        "total_execs_added": internal_block["execs_added"] + external_block["execs_added"],
        "total_execs_updated": internal_block["execs_updated"] + external_block["execs_updated"],
    }

    return {
        "run_id": run_id,
        "tenant_id": str(current_user.tenant_id),
        "mode": payload.mode,
        "eligible_company_count": eligible_company_count,
        "internal": internal_block,
        "external": external_block,
        "combined": combined,
        "compare": compare_counts,
    }


@router.post("/runs/{run_id}/market-test", response_model=MarketTestResponse)
async def run_market_test(
    run_id: UUID,
    payload: MarketTestRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Run the market-test orchestration (Phase 10.4)."""

    service = CompanyResearchService(db)
    actor = current_user.email or current_user.username or "system"

    try:
        result = await service.run_market_test(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            request=payload,
            actor=actor,
        )
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        if msg in {"seed_payload_required", "external_llm_payload_required", "invalid_discovery_mode", "external_payload_required"}:
            raise_app_error(400, "INVALID_REQUEST", msg)
        raise

    await db.commit()
    return result


@router.get("/runs/{run_id}/executives", response_model=List[ExecutiveProspectRead])
async def list_executive_prospects(
    run_id: UUID,
    canonical_company_id: Optional[UUID] = Query(None, description="Filter by canonical company identifier"),
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    verification_status: Optional[str] = Query(None, description="Filter by company verification status"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List executives for a run with evidence pointers and deterministic ordering."""

    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        canonical_company_id=canonical_company_id,
        company_prospect_id=company_prospect_id,
        discovered_by=discovered_by,
        verification_status=verification_status,
    )
    return [ExecutiveProspectRead.model_validate(row) for row in exec_rows]


@router.get("/runs/{run_id}/executives-compare", response_model=ExecutiveCompareResponse)
async def compare_executives(
    run_id: UUID,
    canonical_company_id: Optional[UUID] = Query(None, description="Filter compare view by canonical company"),
    company_prospect_id: Optional[UUID] = Query(None, description="Filter compare view by company prospect"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Compare internal vs external executives for a run/company with evidence pointers."""

    if not canonical_company_id and not company_prospect_id:
        raise HTTPException(status_code=400, detail="company_scope_required")

    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    payload = await service.compare_executives(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        canonical_company_id=canonical_company_id,
        company_prospect_id=company_prospect_id,
    )
    return ExecutiveCompareResponse.model_validate(payload)


@router.get("/runs/{run_id}/executives.json", response_model=List[ExecutiveProspectRead])
async def export_executives_json(
    run_id: UUID,
    canonical_company_id: Optional[UUID] = Query(None, description="Filter by canonical company identifier"),
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    verification_status: Optional[str] = Query(None, description="Filter by company verification status"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export executive prospects as JSON using stable ordering."""

    service = CompanyResearchService(db)
    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        canonical_company_id=canonical_company_id,
        company_prospect_id=company_prospect_id,
        discovered_by=discovered_by,
        verification_status=verification_status,
    )
    return [ExecutiveProspectRead.model_validate(row) for row in exec_rows]


@router.get("/runs/{run_id}/executives.csv")
async def export_executives_csv(
    run_id: UUID,
    canonical_company_id: Optional[UUID] = Query(None, description="Filter by canonical company identifier"),
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    verification_status: Optional[str] = Query(None, description="Filter by company verification status"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export executive prospects as CSV with evidence pointers."""

    service = CompanyResearchService(db)
    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        canonical_company_id=canonical_company_id,
        company_prospect_id=company_prospect_id,
        discovered_by=discovered_by,
        verification_status=verification_status,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "company_name",
            "canonical_company_id",
            "company_prospect_id",
            "name",
            "title",
            "source_label",
            "source_document_id",
            "evidence_source_document_ids",
            "evidence_count",
            "profile_url",
            "linkedin_url",
            "email",
            "location",
            "discovered_by",
            "verification_status",
            "review_status",
            "status",
            "confidence",
        ]
    )

    for row in exec_rows:
        evidence_ids = row.get("evidence_source_document_ids") or []
        writer.writerow(
            [
                row.get("company_name", ""),
                row.get("canonical_company_id"),
                row.get("company_prospect_id"),
                row.get("name", ""),
                row.get("title"),
                row.get("source_label"),
                row.get("source_document_id"),
                "|".join(str(eid) for eid in evidence_ids),
                len(row.get("evidence", []) or []),
                row.get("profile_url"),
                row.get("linkedin_url"),
                row.get("email"),
                row.get("location"),
                row.get("discovered_by"),
                row.get("verification_status"),
                row.get("review_status"),
                row.get("status"),
                row.get("confidence"),
            ]
        )

    stream = io.BytesIO(output.getvalue().encode("utf-8"))
    headers = {"Content-Disposition": f"attachment; filename=run_{run_id}_executives.csv"}
    return StreamingResponse(stream, media_type="text/csv", headers=headers)


@router.post(
    "/runs/{run_id}/executives/enrich_contacts",
    response_model=BulkExecutiveContactEnrichmentResponse,
)
async def bulk_enrich_executive_contacts(
    run_id: UUID,
    payload: BulkExecutiveContactEnrichmentRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Bulk explicit contact enrichment for executives in a run."""

    max_allowed = settings.BULK_ENRICH_MAX_EXECUTIVES
    if payload.executive_ids and len(payload.executive_ids) > max_allowed:
        raise_app_error(
            400,
            "EXEC_ENRICH_LIMIT_EXCEEDED",
            "Too many executive_ids supplied",
            {"max_executive_ids": max_allowed, "provided": len(payload.executive_ids)},
        )

    research_service = CompanyResearchService(db)
    run = await research_service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})

    enrichment_service = ContactEnrichmentService(db)
    enrichment_request = ContactEnrichmentRequest(**payload.model_dump(exclude={"executive_ids"}))

    items: List[BulkExecutiveContactEnrichmentResponseItem] = []
    for exec_id in payload.executive_ids:
        executive = await research_service.repo.get_executive_prospect(current_user.tenant_id, exec_id)
        if not executive or executive.company_research_run_id != run_id:
            raise HTTPException(status_code=404, detail="Executive prospect not found in run")

        results = await enrichment_service.enrich_executive_contacts(
            tenant_id=str(current_user.tenant_id),
            executive_id=exec_id,
            request=enrichment_request,
            performed_by=current_user.email or current_user.username,
        )
        if results is None:
            raise_app_error(
                404,
                "EXEC_NOT_FOUND",
                "Executive prospect not found",
                {"executive_id": str(exec_id)},
            )

        items.append(
            BulkExecutiveContactEnrichmentResponseItem(
                executive_id=exec_id,
                results=results,
            )
        )

    return BulkExecutiveContactEnrichmentResponse(items=items)


@router.patch("/executives/{executive_id}/verification-status", response_model=ExecutiveProspectRead)
async def update_executive_verification_status(
    executive_id: UUID,
    data: ExecutiveVerificationUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Promote executive verification status with audit logging (no downgrades)."""

    service = CompanyResearchService(db)

    try:
        executive = await service.update_executive_verification_status(
            tenant_id=current_user.tenant_id,
            executive_id=executive_id,
            verification_status=data.verification_status,
            actor=current_user.email or current_user.username or "system",
        )
    except ValueError as exc:  # noqa: BLE001
        message = str(exc)
        if message == "invalid_verification_status":
            raise HTTPException(status_code=400, detail="Invalid verification_status")
        if message == "downgrade_not_allowed":
            raise HTTPException(status_code=409, detail="Downgrades not allowed")
        raise

    if not executive:
        raise HTTPException(status_code=404, detail="Executive prospect not found")

    # Re-fetch with evidence pointers to satisfy response model
    payload = None
    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=executive.company_research_run_id,
        company_prospect_id=executive.company_prospect_id,
    )
    for row in exec_rows:
        if row.get("id") == executive_id:
            payload = row
            break

    await db.commit()

    if payload:
        return ExecutiveProspectRead.model_validate(payload)

    # Fallback to minimal response if evidence lookup failed
    return ExecutiveProspectRead.model_validate(
        {
            "id": executive.id,
            "run_id": executive.company_research_run_id,
            "company_prospect_id": executive.company_prospect_id,
            "company_name": getattr(executive, "company_prospect", None).name_normalized if getattr(executive, "company_prospect", None) else "",
            "canonical_company_id": None,
            "discovered_by": executive.discovered_by,
            "provenance": executive.discovered_by,
            "verification_status": executive.verification_status,
            "review_status": getattr(executive, "review_status", "new"),
            "name": executive.name_raw,
            "name_normalized": executive.name_normalized,
            "title": executive.title,
            "profile_url": executive.profile_url,
            "linkedin_url": executive.linkedin_url,
            "email": executive.email,
            "location": executive.location,
            "confidence": float(executive.confidence or 0.0),
            "status": executive.status,
            "source_label": executive.source_label,
            "source_document_id": executive.source_document_id,
            "evidence_source_document_ids": [],
            "evidence": [],
        }
    )


@router.patch("/executives/{executive_id}/review-status", response_model=ExecutiveProspectRead)
async def update_executive_review_status(
    executive_id: UUID,
    data: ExecutiveReviewUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Update executive review gate status with audit logging."""

    service = CompanyResearchService(db)

    try:
        executive = await service.update_executive_review_status(
            tenant_id=current_user.tenant_id,
            executive_id=executive_id,
            review_status=data.review_status,
            actor=current_user.email or current_user.username or "system",
        )
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "invalid_review_status":
            raise HTTPException(status_code=400, detail="Invalid review_status")
        raise

    if not executive:
        raise HTTPException(status_code=404, detail="Executive prospect not found")

    payload = None
    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=executive.company_research_run_id,
        company_prospect_id=executive.company_prospect_id,
    )
    for row in exec_rows:
        if row.get("id") == executive_id:
            payload = row
            break

    await db.commit()

    if payload:
        return ExecutiveProspectRead.model_validate(payload)

    return ExecutiveProspectRead.model_validate(
        {
            "id": executive.id,
            "run_id": executive.company_research_run_id,
            "company_prospect_id": executive.company_prospect_id,
            "company_name": getattr(executive, "company_prospect", None).name_normalized if getattr(executive, "company_prospect", None) else "",
            "canonical_company_id": None,
            "discovered_by": executive.discovered_by,
            "provenance": executive.discovered_by,
            "verification_status": executive.verification_status,
            "review_status": getattr(executive, "review_status", "new"),
            "name": executive.name_raw,
            "name_normalized": executive.name_normalized,
            "title": executive.title,
            "profile_url": executive.profile_url,
            "linkedin_url": executive.linkedin_url,
            "email": executive.email,
            "location": executive.location,
            "confidence": float(executive.confidence or 0.0),
            "status": executive.status,
            "source_label": executive.source_label,
            "source_document_id": executive.source_document_id,
            "evidence_source_document_ids": [],
            "evidence": [],
        }
    )


@router.post(
    "/executives/{executive_id}/enrich_contacts",
    response_model=ExecutiveContactEnrichmentResponse,
)
async def enrich_executive_contacts(
    executive_id: UUID,
    payload: ContactEnrichmentRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Trigger explicit executive contact enrichment with TTL/hash idempotency."""

    enrichment_service = ContactEnrichmentService(db)
    results = await enrichment_service.enrich_executive_contacts(
        tenant_id=str(current_user.tenant_id),
        executive_id=executive_id,
        request=payload,
        performed_by=current_user.email or current_user.username,
    )

    if results is None:
        raise_app_error(
            404,
            "EXEC_NOT_FOUND",
            "Executive prospect not found",
            {"executive_id": str(executive_id)},
        )

    return ExecutiveContactEnrichmentResponse(executive_id=executive_id, results=results)


@router.post(
    "/executives/{executive_id}/pipeline",
    response_model=ExecutivePipelineCreateResponse,
)
async def create_executive_pipeline(
    executive_id: UUID,
    payload: ExecutivePipelineCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Create ATS pipeline records from an accepted executive prospect."""

    service = CompanyResearchService(db)

    try:
        result = await service.create_executive_pipeline(
            tenant_id=current_user.tenant_id,
            executive_id=executive_id,
            assignment_status=payload.assignment_status,
            current_stage_id=payload.current_stage_id,
            role_id=payload.role_id,
            notes=payload.notes,
            actor=current_user.email or current_user.username or "system",
        )
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg in {"review_status_not_accepted", "canonical_not_accepted"}:
            raise_app_error(409, "EXEC_NOT_ACCEPTED", "Executive must be accepted before ATS promotion")
        if msg == "canonical_not_found":
            raise_app_error(404, "CANONICAL_NOT_FOUND", "Canonical executive not found for promotion")
        if msg == "prospect_missing":
            raise_app_error(404, "PROSPECT_NOT_FOUND", "Company prospect not found for executive")
        if msg == "role_missing":
            raise_app_error(400, "ROLE_REQUIRED", "role_id is required on the prospect or payload")
        if msg == "role_mismatch":
            raise_app_error(400, "ROLE_MISMATCH", "role_id does not match prospect role")
        if msg == "stage_not_found":
            raise_app_error(400, "STAGE_NOT_FOUND", "current_stage_id not found for tenant")
        raise

    if result is None:
        raise_app_error(404, "EXEC_NOT_FOUND", "Executive prospect not found")

    await db.commit()
    return result


@router.post("/runs/{run_id}/executives-merge-decision", response_model=ExecutiveMergeDecisionRead)
async def apply_executive_merge_decision(
    run_id: UUID,
    data: ExecutiveMergeDecisionRequest,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Apply evidence-first merge/suppression decision between two executives."""

    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    try:
        decision, created = await service.apply_executive_merge_decision(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            decision_type=data.decision_type,
            left_executive_id=data.left_executive_id,
            right_executive_id=data.right_executive_id,
            note=data.note,
            evidence_source_document_ids=data.evidence_source_document_ids,
            evidence_enrichment_ids=data.evidence_enrichment_ids,
            actor=current_user.email or current_user.username or "system",
        )
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "invalid_decision_type":
            raise HTTPException(status_code=400, detail="Invalid decision_type")
        if msg == "executive_not_found":
            raise HTTPException(status_code=404, detail="Executive prospect not found")
        if msg == "run_mismatch":
            raise HTTPException(status_code=400, detail="Executives not in run")
        if msg == "decision_conflict":
            raise HTTPException(status_code=409, detail="Decision already recorded with different type")
        raise

    await db.commit()

    return ExecutiveMergeDecisionRead.model_validate(
        {
            "id": decision.id,
            "tenant_id": decision.tenant_id,
            "company_research_run_id": decision.company_research_run_id,
            "company_prospect_id": decision.company_prospect_id,
            "canonical_company_id": decision.canonical_company_id,
            "left_executive_id": decision.left_executive_id,
            "right_executive_id": decision.right_executive_id,
            "decision_type": decision.decision_type,
            "note": decision.note,
            "evidence_source_document_ids": decision.evidence_source_document_ids,
            "evidence_enrichment_ids": decision.evidence_enrichment_ids,
            "created_at": decision.created_at,
            "updated_at": decision.updated_at,
            "created_by": decision.created_by,
        }
    )


@router.post("/runs/{run_id}/retry", response_model=CompanyResearchJobRead)
async def retry_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Retry a research run by enqueuing a new job (idempotent)."""
    service = CompanyResearchService(db)
    try:
        job = await service.retry_run(current_user.tenant_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Research run not found")
    await db.commit()
    return CompanyResearchJobRead.model_validate(job)


@router.post("/runs/{run_id}/cancel")
async def cancel_research_run(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Request cancellation for a research run job."""
    service = CompanyResearchService(db)
    result = await service.cancel_run(current_user.tenant_id, run_id)
    await db.commit()

    if result == "not_found":
        raise HTTPException(status_code=404, detail="Research run not found")
    if result == "noop_terminal":
        raise HTTPException(status_code=409, detail="Run already completed")
    if result == "no_active_job":
        raise HTTPException(status_code=404, detail="Active job not found")

    return {"status": "cancel_requested"}


@router.get("/runs/{run_id}/events", response_model=List[ResearchEventRead])
async def list_research_events(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List recent events for a research run."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    events = await service.list_events_for_run(current_user.tenant_id, run_id, limit=limit)
    return [ResearchEventRead.model_validate(e) for e in events]


@router.get("/runs/{run_id}/resolved-entities", response_model=List[ResolvedEntityRead])
async def list_resolved_entities(
    run_id: UUID,
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List resolved canonical entities for a run (deterministic ordering)."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    entities = await service.list_resolved_entities_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        entity_type=entity_type,
    )
    return [ResolvedEntityRead.model_validate(e) for e in entities]


@router.get("/runs/{run_id}/entity-merge-links", response_model=List[EntityMergeLinkRead])
async def list_entity_merge_links(
    run_id: UUID,
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List merge links for resolved entities (deterministic ordering)."""
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    links = await service.list_entity_merge_links_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        entity_type=entity_type,
    )
    return [EntityMergeLinkRead.model_validate(l) for l in links]


@router.get("/canonical-people", response_model=List[CanonicalPersonListItem])
async def list_canonical_people(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List tenant-wide canonical people with linked entity counts."""
    service = CompanyResearchService(db)
    items = await service.list_canonical_people(
        tenant_id=current_user.tenant_id,
        limit=limit,
        offset=offset,
    )
    response: List[CanonicalPersonListItem] = []
    for entry in items:
        person = entry.get("person")
        count = entry.get("linked_entities_count", 0)
        payload = {
            "id": person.id,
            "tenant_id": person.tenant_id,
            "created_at": person.created_at,
            "updated_at": person.updated_at,
            "canonical_full_name": person.canonical_full_name,
            "primary_email": person.primary_email,
            "primary_linkedin_url": person.primary_linkedin_url,
            "linked_entities_count": int(count or 0),
        }
        response.append(CanonicalPersonListItem.model_validate(payload))
    return response


@router.get("/canonical-people/{canonical_person_id}", response_model=CanonicalPersonRead)
async def get_canonical_person_detail(
    canonical_person_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Fetch canonical person detail with emails and links."""
    service = CompanyResearchService(db)
    person = await service.get_canonical_person_detail(current_user.tenant_id, canonical_person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Canonical person not found")
    return CanonicalPersonRead.model_validate(person, from_attributes=True)


@router.get("/canonical-person-links", response_model=List[CanonicalPersonLinkRead])
async def list_canonical_person_links(
    canonical_person_id: Optional[UUID] = Query(None, description="Filter by canonical person"),
    person_entity_id: Optional[UUID] = Query(None, description="Filter by person entity id"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List canonical person links (tenant-scoped)."""
    service = CompanyResearchService(db)
    links = await service.list_canonical_person_links(
        tenant_id=current_user.tenant_id,
        canonical_person_id=canonical_person_id,
        person_entity_id=person_entity_id,
    )
    return [CanonicalPersonLinkRead.model_validate(l, from_attributes=True) for l in links]


@router.get("/canonical-companies", response_model=List[CanonicalCompanyListItem])
async def list_canonical_companies(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List tenant-wide canonical companies with linked entity counts."""
    service = CompanyResearchService(db)
    items = await service.list_canonical_companies(
        tenant_id=current_user.tenant_id,
        limit=limit,
        offset=offset,
    )
    response: List[CanonicalCompanyListItem] = []
    for entry in items:
        company = entry.get("company")
        count = entry.get("linked_entities_count", 0)
        payload = {
            "id": company.id,
            "tenant_id": company.tenant_id,
            "created_at": company.created_at,
            "updated_at": company.updated_at,
            "canonical_name": getattr(company, "canonical_name", None),
            "primary_domain": getattr(company, "primary_domain", None),
            "country_code": getattr(company, "country_code", None),
            "linked_entities_count": int(count or 0),
        }
        response.append(CanonicalCompanyListItem.model_validate(payload))
    return response


@router.get("/canonical-companies/{canonical_company_id}", response_model=CanonicalCompanyRead)
async def get_canonical_company_detail(
    canonical_company_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Fetch canonical company detail with domains and links."""
    service = CompanyResearchService(db)
    company = await service.get_canonical_company_detail(current_user.tenant_id, canonical_company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Canonical company not found")
    return CanonicalCompanyRead.model_validate(company, from_attributes=True)


@router.get("/canonical-company-links", response_model=List[CanonicalCompanyLinkRead])
async def list_canonical_company_links(
    canonical_company_id: Optional[UUID] = Query(None, description="Filter by canonical company"),
    company_entity_id: Optional[UUID] = Query(None, description="Filter by company entity id"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """List canonical company links (tenant-scoped)."""
    service = CompanyResearchService(db)
    links = await service.list_canonical_company_links(
        tenant_id=current_user.tenant_id,
        canonical_company_id=canonical_company_id,
        company_entity_id=company_entity_id,
    )
    return [CanonicalCompanyLinkRead.model_validate(l, from_attributes=True) for l in links]


@router.get("/runs/{run_id}/prospects", response_model=List[CompanyProspectListItem])
async def list_prospects_for_run(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    review_status: Optional[str] = Query(None, description="Filter by review status (new, accepted, hold, rejected)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    exec_search_enabled: Optional[bool] = Query(None, description="Filter by exec_search_enabled flag"),
    order_by: str = Query("ai", description="Ordering mode: 'ai' (relevance) or 'manual' (user priority)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List company prospects for a research run.
    
    Supports filtering by status, minimum relevance score, and ordering by AI or manual ranking.
    
    Ordering modes:
    - "ai": Pinned first, then by AI relevance_score DESC
    - "manual": Pinned first, then by manual_priority ASC (1=highest) NULLS LAST, then relevance
    """
    service = CompanyResearchService(db)
    
    # Verify run exists and belongs to tenant
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospects = await service.list_prospects_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        review_status=review_status,
        verification_status=verification_status,
        discovered_by=discovered_by,
        exec_search_enabled=exec_search_enabled,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    
    return [CompanyProspectListItem.model_validate(p) for p in prospects]


@router.get("/runs/{run_id}/prospects-with-evidence", response_model=List[CompanyProspectWithEvidence])
async def list_prospects_for_run_with_evidence(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    review_status: Optional[str] = Query(None, description="Filter by review status (new, accepted, hold, rejected)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    exec_search_enabled: Optional[bool] = Query(None, description="Filter by exec_search_enabled flag"),
    order_by: str = Query("ai", description="Ordering mode: 'ai' (relevance) or 'manual' (user priority)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List company prospects for a research run with evidence and source document details.
    
    Returns prospects with nested evidence records and their linked source documents.
    Uses efficient joins to avoid N+1 queries.
    
    Ordering modes:
    - "ai": Pinned first, then by AI relevance_score DESC
    - "manual": Pinned first, then by manual_priority ASC (1=highest) NULLS LAST, then relevance
    """
    service = CompanyResearchService(db)
    
    # Verify run exists and belongs to tenant
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    prospects = await service.list_prospects_for_run_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        review_status=review_status,
        verification_status=verification_status,
        discovered_by=discovered_by,
        exec_search_enabled=exec_search_enabled,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    
    return [CompanyProspectWithEvidence.model_validate(p) for p in prospects]


@router.get("/runs/{run_id}/prospects-ranked", response_model=List[CompanyProspectRanking])
async def rank_prospects_for_run(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    review_status: Optional[str] = Query(None, description="Filter by review status (new, accepted, hold, rejected)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    exec_search_enabled: Optional[bool] = Query(None, description="Filter by exec_search_enabled flag"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Return deterministic, evidence-backed prospect rankings with explainability."""

    service = CompanyResearchService(db)

    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    ranked = await service.rank_prospects_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        limit=limit,
        offset=offset,
    )
    ranked_items = [CompanyProspectRanking.model_validate(item) for item in ranked]
    filtered = _apply_rank_filters(
        ranked_items,
        min_score=None,
        has_hq=False,
        has_ownership=False,
        has_industry=False,
        review_status=review_status,
        verification_status=verification_status,
        discovered_by=discovered_by,
        exec_search_enabled=exec_search_enabled,
    )
    return filtered


@router.get("/runs/{run_id}/prospects-ranked.json", response_model=List[CompanyProspectRanking])
async def export_ranked_prospects_json(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    min_score: Optional[float] = Query(None, ge=0.0, le=2.0, description="Minimum computed score after ranking"),
    has_hq: bool = Query(False, description="Require HQ country signal"),
    has_ownership: bool = Query(False, description="Require ownership signal"),
    has_industry: bool = Query(False, description="Require industry keywords signal"),
    review_status: Optional[str] = Query(None, description="Filter by review status (new, accepted, hold, rejected)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    exec_search_enabled: Optional[bool] = Query(None, description="Filter by exec_search_enabled flag"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export ranked prospects as JSON with optional explainability filters."""

    service = CompanyResearchService(db)
    ranked = await _get_filtered_rankings(
        service,
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        limit=limit,
        offset=offset,
        min_score=min_score,
        has_hq=has_hq,
        has_ownership=has_ownership,
        has_industry=has_industry,
        review_status=review_status,
        verification_status=verification_status,
        discovered_by=discovered_by,
        exec_search_enabled=exec_search_enabled,
    )

    return ranked


@router.get("/runs/{run_id}/prospects-ranked.csv")
async def export_ranked_prospects_csv(
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status (new, approved, rejected, duplicate, converted)"),
    min_relevance_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum AI relevance score"),
    min_score: Optional[float] = Query(None, ge=0.0, le=2.0, description="Minimum computed score after ranking"),
    has_hq: bool = Query(False, description="Require HQ country signal"),
    has_ownership: bool = Query(False, description="Require ownership signal"),
    has_industry: bool = Query(False, description="Require industry keywords signal"),
    review_status: Optional[str] = Query(None, description="Filter by review status (new, accepted, hold, rejected)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    discovered_by: Optional[str] = Query(None, description="Filter by discovery provenance"),
    exec_search_enabled: Optional[bool] = Query(None, description="Filter by exec_search_enabled flag"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export ranked prospects as CSV with explainability rollup."""

    service = CompanyResearchService(db)
    ranked = await _get_filtered_rankings(
        service,
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        status=status,
        min_relevance_score=min_relevance_score,
        limit=limit,
        offset=offset,
        min_score=min_score,
        has_hq=has_hq,
        has_ownership=has_ownership,
        has_industry=has_industry,
        review_status=review_status,
        verification_status=verification_status,
        discovered_by=discovered_by,
        exec_search_enabled=exec_search_enabled,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "rank",
            "company_name",
            "score_total",
            "review_status",
            "verification_status",
            "discovered_by",
            "exec_search_enabled",
            "hq_country",
            "ownership_signal",
            "industry_keywords",
            "why_included",
            "evidence_source_document_ids",
        ]
    )

    for idx, item in enumerate(ranked, start=1):
        ownership = ""
        industry = ""
        evidence_ids = set()
        signal_parts = []

        for signal in item.why_included or []:
            evidence_ids.add(str(signal.source_document_id))
            val = signal.value_normalized or signal.value
            if signal.field_key == "ownership_signal":
                ownership = str(val or "")
            if signal.field_key == "industry_keywords":
                if isinstance(signal.value, list):
                    industry = ";".join(str(v) for v in signal.value)
                else:
                    industry = str(signal.value or "")
            signal_parts.append(f"{signal.field_key}={val}")

        writer.writerow(
            [
                idx,
                item.name_normalized,
                f"{float(item.computed_score):.6f}",
                getattr(item, "review_status", ""),
                getattr(item, "verification_status", ""),
                getattr(item, "discovered_by", ""),
                str(getattr(item, "exec_search_enabled", False)),
                item.hq_country or "",
                ownership,
                industry,
                "; ".join(signal_parts),
                ";".join(sorted(evidence_ids)),
            ]
        )

    payload = output.getvalue()
    filename = f"prospects-ranked-{run_id}.csv"
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/runs/{run_id}/executives-ranked", response_model=List[ExecutiveRanking])
async def rank_executives_for_run(
    run_id: UUID,
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    provenance: Optional[str] = Query(None, description="Filter by provenance (internal, external, both)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status (unverified, partial, verified)"),
    q: Optional[str] = Query(None, description="Case-insensitive search on display_name or title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Return deterministic, explainable executive rankings."""

    service = CompanyResearchService(db)
    ranked = await _get_ranked_executives(
        service,
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        company_prospect_id=company_prospect_id,
        provenance=provenance,
        verification_status=verification_status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return ranked


@router.get("/runs/{run_id}/executives-ranked.json", response_model=List[ExecutiveRanking])
async def export_ranked_executives_json(
    run_id: UUID,
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    provenance: Optional[str] = Query(None, description="Filter by provenance (internal, external, both)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status (unverified, partial, verified)"),
    q: Optional[str] = Query(None, description="Case-insensitive search on display_name or title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export ranked executives as JSON with explainability."""

    service = CompanyResearchService(db)
    ranked = await _get_ranked_executives(
        service,
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        company_prospect_id=company_prospect_id,
        provenance=provenance,
        verification_status=verification_status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return ranked


@router.get("/runs/{run_id}/executives-ranked.csv")
async def export_ranked_executives_csv(
    run_id: UUID,
    company_prospect_id: Optional[UUID] = Query(None, description="Filter by company prospect identifier"),
    provenance: Optional[str] = Query(None, description="Filter by provenance (internal, external, both)"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status (unverified, partial, verified)"),
    q: Optional[str] = Query(None, description="Case-insensitive search on display_name or title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export ranked executives as CSV with explainability rollup."""

    service = CompanyResearchService(db)
    ranked = await _get_ranked_executives(
        service,
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        company_prospect_id=company_prospect_id,
        provenance=provenance,
        verification_status=verification_status,
        q=q,
        limit=limit,
        offset=offset,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "rank_position",
            "rank_score",
            "executive_id",
            "company_id",
            "display_name",
            "title",
            "provenance",
            "verification_status",
            "reason_codes",
            "evidence_source_document_ids",
        ]
    )

    for item in ranked:
        reason_codes = ";".join([reason.code for reason in (item.why_ranked or [])])
        evidence_ids = ";".join(sorted(str(eid) for eid in (item.evidence_source_document_ids or [])))

        writer.writerow(
            [
                item.rank_position,
                f"{float(item.rank_score):.6f}",
                item.executive_id,
                item.company_prospect_id,
                item.display_name,
                item.title or "",
                item.provenance or "",
                item.verification_status or "",
                reason_codes,
                evidence_ids,
            ]
        )

    payload = output.getvalue()
    filename = f"executives-ranked-{run_id}.csv"
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/runs/{run_id}/export-pack.zip", response_class=StreamingResponse)
async def export_run_pack(
    run_id: UUID,
    include_html: bool = Query(False, description="Include an HTML print view in the archive"),
    max_companies: int = Query(
        CompanyResearchService.EXPORT_DEFAULT_MAX_COMPANIES,
        ge=1,
        le=CompanyResearchService.EXPORT_MAX_COMPANIES,
        description="Maximum companies to include in the pack",
    ),
    max_executives: int = Query(
        CompanyResearchService.EXPORT_DEFAULT_MAX_EXECUTIVES,
        ge=1,
        le=CompanyResearchService.EXPORT_MAX_EXECUTIVES,
        description="Maximum executives to include in the pack",
    ),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Export a deterministic run pack (JSON + CSVs + optional HTML) as a ZIP."""

    service = CompanyResearchService(db)
    try:
        _pack, zip_bytes, _ = await service.build_run_export_pack(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            include_html=include_html,
            max_companies=max_companies,
            max_executives=max_executives,
        )
    except ValueError as exc:  # noqa: BLE001
        msg = str(exc)
        if msg == "research_run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        if msg == "export_param_invalid":
            raise_app_error(
                400,
                "EXPORT_LIMIT_INVALID",
                "max_companies and max_executives must be >= 1",
                {"max_companies": max_companies, "max_executives": max_executives},
            )
        if msg == "export_pack_too_large":
            raise_app_error(
                413,
                "EXPORT_ZIP_TOO_LARGE",
                "export pack exceeds maximum allowed size",
                {"max_zip_bytes": CompanyResearchService.EXPORT_MAX_ZIP_BYTES},
            )
        raise

    filename = f"run_{run_id}_pack.zip"
    sha_value = hashlib.sha256(zip_bytes).hexdigest()

    export_record = await service.register_export_pack(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        file_name=filename,
        zip_bytes=zip_bytes,
        sha256=sha_value,
    )
    await db.commit()

    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(io.BytesIO(zip_bytes), media_type="application/zip", headers=headers)


@router.get("/runs/{run_id}/export-packs", response_model=List[ExportPackRead])
async def list_export_packs(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})

    records = await service.list_export_packs_for_run(current_user.tenant_id, run_id)
    return [ExportPackRead.model_validate(rec) for rec in records]


@router.get("/export-packs/{export_id}", response_class=StreamingResponse)
async def download_export_pack(
    export_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(db)
    try:
        record, data = await service.get_export_pack_for_download(current_user.tenant_id, export_id)
    except ValueError as exc:  # noqa: BLE001
        if str(exc) in {"export_file_missing", "export_pointer_escape", "export_pointer_invalid"}:
            raise_app_error(404, "EXPORT_NOT_FOUND", "Export pack not found", {"export_id": str(export_id)})
        raise

    if not record:
        raise_app_error(404, "EXPORT_NOT_FOUND", "Export pack not found", {"export_id": str(export_id)})

    filename = record.file_name or f"export_{export_id}.zip"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(io.BytesIO(data), media_type="application/zip", headers=headers)


@router.get("/runs/{run_id}/evidence-bundle", response_class=StreamingResponse)
async def download_evidence_bundle(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Generate a deterministic evidence bundle for a research run."""

    service = CompanyResearchService(db)
    try:
        bundle_bytes, _manifest, _files = await service.build_evidence_bundle(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
        )
    except ValueError as exc:  # noqa: BLE001
        if str(exc) == "research_run_not_found":
            raise_app_error(404, "RUN_NOT_FOUND", "Research run not found", {"run_id": str(run_id)})
        raise

    filename = f"run_{run_id}_evidence_bundle.zip"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(io.BytesIO(bundle_bytes), media_type="application/zip", headers=headers)


@router.patch("/runs/{run_id}", response_model=CompanyResearchRunRead)
async def update_research_run(
    run_id: UUID,
    data: CompanyResearchRunUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a research run (status, description, config, etc.).
    """
    service = CompanyResearchService(db)
    
    run = await service.update_research_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        data=data,
    )
    
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    await db.commit()
    return CompanyResearchRunRead.model_validate(run)


# ============================================================================
# Company Prospect Endpoints
# ============================================================================

@router.post("/prospects", response_model=CompanyProspectRead)
async def create_prospect(
    data: CompanyProspectCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new company prospect (typically called by AI/system).
    """
    service = CompanyResearchService(db)
    
    prospect = await service.create_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectRead.model_validate(prospect)


@router.get("/prospects/{prospect_id}", response_model=CompanyProspectRead)
async def get_prospect(
    prospect_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a company prospect by ID.
    """
    service = CompanyResearchService(db)
    
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    return CompanyProspectRead.model_validate(prospect)


@router.patch("/prospects/{prospect_id}/manual", response_model=CompanyProspectRead)
async def update_prospect_manual_fields(
    prospect_id: UUID,
    data: CompanyProspectUpdateManual,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update manual override fields for a company prospect.
    
    This endpoint ONLY updates:
    - manual_priority (1 = highest priority)
    - manual_notes
    - is_pinned
    - status
    
    AI-calculated fields (relevance_score, evidence_score) are NEVER touched by this endpoint.
    """
    service = CompanyResearchService(db)
    
    prospect = await service.update_prospect_manual_fields(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        data=data,
    )
    
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    await db.commit()
    return CompanyProspectRead.model_validate(prospect)


@router.patch("/prospects/{prospect_id}/review-status", response_model=CompanyProspectRead)
async def update_prospect_review_status(
    prospect_id: UUID,
    data: CompanyProspectReviewUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Update review gate status for a company prospect with audit logging."""

    service = CompanyResearchService(db)

    try:
        prospect = await service.update_prospect_review_status(
            tenant_id=current_user.tenant_id,
            prospect_id=prospect_id,
            review_status=data.review_status,
            exec_search_enabled=data.exec_search_enabled,
            actor=current_user.email or current_user.username or "system",
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review_status")

    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")

    await db.commit()
    return CompanyProspectRead.model_validate(prospect)


# ============================================================================
# Evidence Endpoints
# ============================================================================

@router.post("/prospects/{prospect_id}/evidence", response_model=CompanyProspectEvidenceRead)
async def add_evidence_to_prospect(
    prospect_id: UUID,
    data: CompanyProspectEvidenceCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Add evidence to a company prospect.
    
    Evidence sources: ranking_list, association_directory, regulatory_register, etc.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    # Ensure evidence belongs to the correct prospect
    data.company_prospect_id = prospect_id
    
    evidence = await service.add_evidence_to_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectEvidenceRead.model_validate(evidence)


@router.get("/prospects/{prospect_id}/evidence", response_model=List[CompanyProspectEvidenceRead])
async def list_evidence_for_prospect(
    prospect_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List all evidence records for a specific company prospect.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    evidence_list = await service.list_evidence_for_prospect(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
    )
    
    return [CompanyProspectEvidenceRead.model_validate(e) for e in evidence_list]


# ============================================================================
# Metric Endpoints
# ============================================================================

@router.post("/prospects/{prospect_id}/metrics", response_model=CompanyProspectMetricRead)
async def add_metric_to_prospect(
    prospect_id: UUID,
    data: CompanyProspectMetricCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a metric to a company prospect.
    
    Metrics: total_assets, revenue, employees, etc. with currency conversion to USD.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    # Ensure metric belongs to the correct prospect
    data.company_prospect_id = prospect_id
    
    metric = await service.add_metric_to_prospect(
        tenant_id=current_user.tenant_id,
        data=data,
    )
    
    await db.commit()
    return CompanyProspectMetricRead.model_validate(metric)


@router.get("/prospects/{prospect_id}/metrics", response_model=List[CompanyProspectMetricRead])
async def list_metrics_for_prospect(
    prospect_id: UUID,
    metric_type: Optional[str] = Query(None, description="Filter by metric type (total_assets, revenue, employees, etc.)"),
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    List all metrics for a specific company prospect.
    
    Optionally filter by metric_type.
    """
    service = CompanyResearchService(db)
    
    # Verify prospect exists
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Company prospect not found")
    
    metrics = await service.list_metrics_for_prospect(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        metric_type=metric_type,
    )
    
    return [CompanyProspectMetricRead.model_validate(m) for m in metrics]


# ============================================================================
# DEV/TEST ENDPOINTS - Remove in production
# ============================================================================

@router.post("/runs/{run_id}/seed-dummy-prospects", response_model=List[CompanyProspectRead])
async def seed_dummy_prospects(
    run_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    [DEV ONLY] Create 5 dummy company prospects for testing.
    
    This endpoint creates realistic fake data to test listing and sorting logic.
    Remove or protect this endpoint in production.
    """
    service = CompanyResearchService(db)
    
    # Verify run exists
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Create 5 dummy prospects with varied scores and priorities
    dummy_data = [
        {
            "name": "ABC Financial Services Ltd",
            "website": "https://abcfinancial.example.com",
            "headquarters_location": "Mumbai, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Leading NBFC specializing in vehicle financing",
            "relevance_score": 0.92,
            "evidence_score": 0.88,
            "manual_priority": None,
            "is_pinned": False,
        },
        {
            "name": "XYZ Capital & Investments",
            "website": "https://xyzcapital.example.com",
            "headquarters_location": "Bangalore, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Mid-sized NBFC focused on SME lending",
            "relevance_score": 0.85,
            "evidence_score": 0.82,
            "manual_priority": 3,
            "is_pinned": False,
        },
        {
            "name": "Premier Finance Corporation",
            "website": "https://premierfinance.example.com",
            "headquarters_location": "Delhi, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Large NBFC with strong retail presence",
            "relevance_score": 0.78,
            "evidence_score": 0.75,
            "manual_priority": 2,
            "is_pinned": False,
        },
        {
            "name": "Strategic NBFC Holdings",
            "website": "https://strategicnbfc.example.com",
            "headquarters_location": "Pune, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Key strategic NBFC with diversified portfolio",
            "relevance_score": 0.71,
            "evidence_score": 0.68,
            "manual_priority": 1,
            "is_pinned": True,
        },
        {
            "name": "Omega Credit Solutions",
            "website": "https://omegacredit.example.com",
            "headquarters_location": "Chennai, India",
            "country_code": "IN",
            "industry_sector": "NBFC",
            "brief_description": "Emerging NBFC in microfinance sector",
            "relevance_score": 0.65,
            "evidence_score": 0.61,
            "manual_priority": None,
            "is_pinned": False,
        },
    ]
    
    created_prospects = []
    for data in dummy_data:
        prospect_create = CompanyProspectCreate(
            company_research_run_id=run_id,
            name=data["name"],
            name_normalized=data["name"].lower().replace("ltd", "").replace(".", "").strip(),
            website=data["website"],
            headquarters_location=data["headquarters_location"],
            country_code=data["country_code"],
            industry_sector=data["industry_sector"],
            brief_description=data["brief_description"],
            relevance_score=data["relevance_score"],
            evidence_score=data["evidence_score"],
            manual_priority=data["manual_priority"],
            is_pinned=data["is_pinned"],
            status="new",
        )
        
        prospect = await service.create_prospect(
            tenant_id=current_user.tenant_id,
            data=prospect_create,
        )
        created_prospects.append(prospect)
    
    await db.commit()
    
    return [CompanyProspectRead.model_validate(p) for p in created_prospects]

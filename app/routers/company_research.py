"""
Company Research Router - API endpoints.

Provides REST API for company discovery and agentic sourcing.
Phase 1: Backend structures, no external AI orchestration yet.
"""

import base64
import binascii
import csv
import io
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.services.company_research_service import CompanyResearchService
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
    ExecutiveProspectRead,
    CompanyProspectUpdateManual,
    CompanyProspectReviewUpdate,
    ExecutiveVerificationUpdate,
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
)


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


class ExecutiveEligibilityItem(BaseModel):
    id: UUID
    name_normalized: str
    status: str
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
            status=prospect.status,
            exec_search_enabled=prospect.exec_search_enabled,
        )
        for prospect in eligible
    ]


@router.post("/runs/{run_id}/executive-discovery/run")
async def run_executive_discovery(
    run_id: UUID,
    payload: ExecutiveDiscoveryRunPayload,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """Start executive discovery for a run using internal stub and/or external payloads."""

    service = CompanyResearchService(db)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    if payload.mode not in {"internal", "external", "both"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    eligible_companies = await service.list_executive_eligible_companies(current_user.tenant_id, run_id)
    eligible_company_count = len(eligible_companies)

    internal_result = None
    external_result = None

    if payload.mode in {"internal", "both"}:
        internal_result = await service.run_internal_executive_discovery(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
        )

    if payload.mode in {"external", "both"}:
        if not payload.payload:
            raise HTTPException(status_code=400, detail="Missing payload for external mode")
        if not payload.provider:
            raise HTTPException(status_code=400, detail="provider is required for external mode")
        engine = payload.engine or "external"
        try:
            external_result = await service.ingest_executive_llm_json_payload(
                tenant_id=current_user.tenant_id,
                run_id=run_id,
                payload=payload.payload,
                provider=payload.provider,
                model_name=payload.model,
                title=payload.title,
                engine=engine,
                request_payload=payload.payload,
            )
        except ValueError as exc:  # noqa: BLE001
            message = str(exc)
            status_code = 400
            if message == "run_not_found":
                status_code = 404
            raise HTTPException(status_code=status_code, detail=message)

    await db.commit()

    def _add_source_label(items: list[dict] | None, source: str) -> list[dict]:
        return [{**item, "source": source} for item in (items or [])]

    combined_summaries: list[dict] = []
    if internal_result:
        combined_summaries.extend(_add_source_label(internal_result.get("company_summaries"), "internal"))
    if external_result:
        combined_summaries.extend(_add_source_label(external_result.get("company_summaries"), "external"))

    processed_company_count = 0
    if internal_result:
        processed_company_count = max(processed_company_count, int(internal_result.get("processed_company_count", 0)))
    if external_result:
        processed_company_count = max(processed_company_count, int(external_result.get("processed_company_count", 0)))

    skipped = None
    if payload.mode == "internal":
        skipped = (internal_result or {}).get("skipped")

    return {
        "mode": payload.mode,
        "eligible_company_count": eligible_company_count,
        "processed_company_count": processed_company_count,
        "company_summaries": combined_summaries,
        "internal_result": internal_result,
        "external_result": external_result,
        "skipped": skipped,
    }


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
                row.get("status"),
                row.get("confidence"),
            ]
        )

    stream = io.BytesIO(output.getvalue().encode("utf-8"))
    headers = {"Content-Disposition": f"attachment; filename=run_{run_id}_executives.csv"}
    return StreamingResponse(stream, media_type="text/csv", headers=headers)


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

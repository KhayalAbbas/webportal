from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.models.company import Company
from app.models.company_research import CompanyProspect, ExecutiveProspect
from app.models.pipeline_stage import PipelineStage
from app.models.role import Role
from app.services.company_research_service import CompanyResearchService
from app.services.discovery_provider import ExternalProviderConfigError, get_discovery_provider
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.schemas.company_research import CompanyResearchRunCreate, CompanyProspectUpdateManual

router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


async def _get_default_role(session: AsyncSession, tenant_id: UUID) -> Optional[dict]:
    query = (
        select(Role, Company.name.label("company_name"))
        .join(Company, Company.id == Role.company_id)
        .where(Role.tenant_id == tenant_id)
        .order_by(Company.name.asc(), Role.created_at.asc())
    )
    result = await session.execute(query)
    row = result.first()
    if not row:
        return None
    return {
        "id": str(row.Role.id),
        "title": row.Role.title,
        "company_name": row.company_name,
    }


async def _count_review_states(session: AsyncSession, tenant_id: UUID, run_id: UUID) -> dict:
    query = (
        select(
            func.count(CompanyProspect.id).label("total"),
            func.count().filter(CompanyProspect.review_status == "accepted").label("accepted"),
            func.count().filter(CompanyProspect.review_status == "hold").label("hold"),
            func.count().filter(CompanyProspect.review_status == "rejected").label("rejected"),
        )
        .where(
            CompanyProspect.tenant_id == tenant_id,
            CompanyProspect.company_research_run_id == run_id,
        )
    )
    result = await session.execute(query)
    row = result.first()
    return {
        "total": int(row.total or 0),
        "accepted": int(row.accepted or 0),
        "hold": int(row.hold or 0),
        "rejected": int(row.rejected or 0),
    }


async def _count_executives(session: AsyncSession, tenant_id: UUID, run_id: UUID) -> int:
    query = select(func.count(ExecutiveProspect.id)).where(
        ExecutiveProspect.tenant_id == tenant_id,
        ExecutiveProspect.company_research_run_id == run_id,
    )
    result = await session.execute(query)
    return int(result.scalar() or 0)


@router.get("/ui/research", response_class=HTMLResponse)
async def research_index(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Research index with run list and new-entry CTA."""

    service = CompanyResearchService(session)
    runs = await service.list_research_runs(current_user.tenant_id, limit=100)

    rows = []
    for run in runs:
        review_counts = await _count_review_states(session, current_user.tenant_id, run.id)
        exec_count = await _count_executives(session, current_user.tenant_id, run.id)
        rows.append(
            {
                "id": str(run.id),
                "name": run.name,
                "status": run.status,
                "sector": run.sector,
                "region_scope": run.region_scope,
                "created_at": run.created_at,
                "prospects_total": review_counts["total"],
                "prospects_accepted": review_counts["accepted"],
                "exec_count": exec_count,
            }
        )

    return templates.TemplateResponse(
        "research_index.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "research",
            "runs": rows,
            "success_message": success_message,
            "error_message": error_message,
        },
    )


@router.get("/ui/research/new", response_class=HTMLResponse)
async def research_new_form(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    error_message: Optional[str] = None,
):
    default_role = await _get_default_role(session, current_user.tenant_id)
    return templates.TemplateResponse(
        "research_new.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "research",
            "default_role": default_role,
            "error_message": error_message,
        },
    )

@router.post("/ui/research/new")
async def research_new_submit(
    request: Request,
    industry: str = Form(...),
    country_region: str = Form(""),
    position: str = Form(""),
    keywords: str = Form(""),
    exclusions: str = Form(""),
    discovery_mode: str = Form("internal"),
    search_provider: str = Form("none"),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    default_role = await _get_default_role(session, current_user.tenant_id)
    if not default_role:
        return RedirectResponse(
            url="/ui/research/new?error_message=Create a role first via Roles page.",
            status_code=303,
        )

    region_list: List[str] = [r.strip().upper() for r in country_region.split(",") if r.strip()]
    config = {
        "workspace": {
            "industry": industry,
            "country_region": country_region,
            "position": position,
            "keywords": keywords,
            "exclusions": exclusions,
            "ui_version": "phase_11_1",
        },
        "discovery": {
            "mode": discovery_mode,
            "search_provider": search_provider,
        },
    }

    name_parts = [part for part in [position, industry] if part]
    run_name = " / ".join(name_parts) if name_parts else "Research Workspace"
    description_parts = []
    if keywords:
        description_parts.append(f"keywords: {keywords}")
    if exclusions:
        description_parts.append(f"exclude: {exclusions}")
    description = "; ".join(description_parts) if description_parts else None

    needs_external = discovery_mode in {"external", "both"}
    needs_search = search_provider == "enabled"

    try:
        if needs_external:
            provider = get_discovery_provider("xai_grok")
            if provider and hasattr(provider, "validate_config"):
                provider.validate_config()
        if needs_search:
            provider = get_discovery_provider("google_cse")
            if provider and hasattr(provider, "validate_config"):
                provider.validate_config()
    except ExternalProviderConfigError as exc:
        return RedirectResponse(
            url=f"/ui/research/new?error_message=External discovery not configured: {str(exc)}",
            status_code=303,
        )

    service = CompanyResearchService(session)
    try:
        run = await service.create_research_run(
            tenant_id=current_user.tenant_id,
            data=CompanyResearchRunCreate(
                role_mandate_id=UUID(default_role["id"]),
                name=run_name[:255],
                description=description,
                sector=industry or "general",
                region_scope=region_list or None,
                config=config,
                status="active",
            ),
            created_by_user_id=current_user.user_id,
        )
        await session.flush()

        discovery_request = {
            "query": " ".join(part for part in [position, industry] if part).strip() or industry or "company discovery",
            "industry": industry or None,
            "region": region_list[0] if region_list else None,
            "notes": "; ".join(part for part in [keywords, exclusions] if part) or None,
            "max_companies": 8,
        }

        search_request = {
            "query": discovery_request["query"],
            "country": region_list[0] if region_list else None,
            "num_results": 5,
        }

        if needs_external:
            await service.run_discovery_provider(
                tenant_id=current_user.tenant_id,
                run_id=run.id,
                provider_key="xai_grok",
                request_payload=discovery_request,
            )

        if needs_search:
            await service.run_discovery_provider(
                tenant_id=current_user.tenant_id,
                run_id=run.id,
                provider_key="google_cse",
                request_payload=search_request,
            )

        await service.start_run(current_user.tenant_id, run.id)
        await session.commit()
    except ExternalProviderConfigError as exc:
        await session.rollback()
        return RedirectResponse(
            url=f"/ui/research/new?error_message=External discovery not configured: {str(exc)}",
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        msg = str(exc)
        return RedirectResponse(
            url=f"/ui/research/new?error_message={msg}",
            status_code=303,
        )

    return RedirectResponse(url=f"/ui/research/runs/{run.id}", status_code=303)


@router.get("/ui/research/runs/{run_id}", response_class=HTMLResponse)
async def research_workspace(
    request: Request,
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
):
    service = CompanyResearchService(session)
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")

    prospects = await service.list_prospects_for_run_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        order_by="manual",
        limit=300,
    )

    prospect_rows = []
    for prospect in prospects:
        evidence = getattr(prospect, "evidence", []) or []
        primary_evidence_url = None
        if evidence:
            first_ev = evidence[0]
            primary_evidence_url = first_ev.source_url
            if not primary_evidence_url and getattr(first_ev, "source_document", None):
                primary_evidence_url = first_ev.source_document.url

        prospect_rows.append(
            {
                "id": str(prospect.id),
                "name": prospect.name_normalized or prospect.name_raw,
                "website_url": prospect.website_url,
                "hq_city": prospect.hq_city,
                "hq_country": prospect.hq_country,
                "sector": prospect.sector,
                "relevance_score": prospect.relevance_score,
                "review_status": prospect.review_status,
                "exec_search_enabled": prospect.exec_search_enabled,
                "manual_priority": prospect.manual_priority,
                "primary_evidence_url": primary_evidence_url,
            }
        )

    exec_rows = await service.list_executive_prospects_with_evidence(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
    )

    executive_rows = []
    for exec_row in exec_rows:
        evidence = exec_row.get("evidence") or []
        evidence_url = None
        if exec_row.get("linkedin_url"):
            evidence_url = exec_row.get("linkedin_url")
        elif evidence:
            doc = evidence[0].get("source_document") if isinstance(evidence[0], dict) else None
            evidence_url = evidence[0].get("source_url") if isinstance(evidence[0], dict) else None
            if not evidence_url and doc:
                evidence_url = doc.get("url")

        executive_rows.append(
            {
                "id": str(exec_row.get("id")),
                "company": exec_row.get("company_name"),
                "name": exec_row.get("name"),
                "title": exec_row.get("title"),
                "evidence_url": evidence_url,
                "review_status": exec_row.get("review_status"),
            }
        )

    eligible_companies = await service.list_executive_eligible_companies(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
    )

    pipeline_stage_rows: list[dict] = []
    stage_query = (
        select(PipelineStage)
        .where(PipelineStage.tenant_id == current_user.tenant_id)
        .order_by(PipelineStage.order_index.asc(), PipelineStage.created_at.asc())
    )
    stage_result = await session.execute(stage_query)
    for stage in stage_result.scalars().all():
        pipeline_stage_rows.append({"id": str(stage.id), "name": stage.name, "code": stage.code})

    return templates.TemplateResponse(
        "research_workspace.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "research",
            "run": {
                "id": str(run.id),
                "name": run.name,
                "status": run.status,
                "sector": run.sector,
                "region_scope": run.region_scope,
                "config": run.config or {},
                "description": run.description,
            },
            "prospects": prospect_rows,
            "executives": executive_rows,
            "has_execs": len(executive_rows) > 0,
            "eligible_exec_companies": len(eligible_companies),
            "pipeline_stages": pipeline_stage_rows,
            "success_message": success_message,
            "error_message": error_message,
        },
    )


@router.post("/ui/research/prospects/{prospect_id}/review")
async def research_prospect_review(
    prospect_id: UUID,
    run_id: UUID = Form(...),
    review_status: str = Form(...),
    enable_exec_search: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(session)
    try:
        await service.update_prospect_review_status(
            tenant_id=current_user.tenant_id,
            prospect_id=prospect_id,
            review_status=review_status,
            exec_search_enabled=True if enable_exec_search == "true" else None,
            actor=current_user.email or current_user.username or "system",
        )
        await session.commit()
    except ValueError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Invalid review status")

    return RedirectResponse(url=f"/ui/research/runs/{run_id}?success_message=Updated", status_code=303)


@router.post("/ui/research/prospects/{prospect_id}/rank")
async def research_prospect_rank(
    prospect_id: UUID,
    run_id: UUID = Form(...),
    direction: str = Form(...),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(session)
    prospect = await service.get_prospect(current_user.tenant_id, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    current_priority = prospect.manual_priority or 1000
    if direction == "up":
        new_priority = max(1, current_priority - 1)
    else:
        new_priority = current_priority + 1

    await service.update_prospect_manual_fields(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        data=CompanyProspectUpdateManual(manual_priority=new_priority),
    )
    await session.commit()

    return RedirectResponse(url=f"/ui/research/runs/{run_id}?success_message=Ranking updated", status_code=303)


@router.post("/ui/research/runs/{run_id}/executive-discovery")
async def research_exec_discovery(
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(session)
    eligible = await service.list_executive_eligible_companies(current_user.tenant_id, run_id)
    if not eligible:
        return RedirectResponse(
            url=f"/ui/research/runs/{run_id}?error_message=Accept at least one company with exec search enabled",
            status_code=303,
        )

    await service.run_internal_executive_discovery(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
    )
    await session.commit()
    return RedirectResponse(url=f"/ui/research/runs/{run_id}?success_message=Executive discovery started", status_code=303)


@router.post("/ui/research/executives/pipeline")
async def research_exec_pipeline(
    run_id: UUID = Form(...),
    executive_ids: List[str] = Form(...),
    stage_id: Optional[str] = Form(None),
    assignment_status: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    service = CompanyResearchService(session)
    if not executive_ids:
        return RedirectResponse(
            url=f"/ui/research/runs/{run_id}?error_message=Select at least one executive",
            status_code=303,
        )

    promoted = 0
    reused = 0
    for exec_id in executive_ids:
        try:
            result = await service.create_executive_pipeline(
                tenant_id=current_user.tenant_id,
                executive_id=UUID(exec_id),
                assignment_status=assignment_status,
                current_stage_id=UUID(stage_id) if stage_id else None,
                role_id=None,
                notes=None,
                actor=current_user.email or current_user.username or "system",
            )
            if result:
                promoted += int(result.get("promoted_count", 0) or 0)
                reused += int(result.get("reused_count", 0) or 0)
        except ValueError as exc:  # noqa: BLE001
            await session.rollback()
            return RedirectResponse(
                url=f"/ui/research/runs/{run_id}?error_message={str(exc)}",
                status_code=303,
            )

    await session.commit()
    msg = f"Promoted {promoted} (reused {reused})"
    return RedirectResponse(url=f"/ui/research/runs/{run_id}?success_message={msg}", status_code=303)


@router.get("/ui/research/runs/{run_id}/steps")
async def research_run_steps(
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """Lightweight JSON view of run steps (debug)."""

    service = CompanyResearchService(session)
    try:
        steps = await service.list_run_steps(current_user.tenant_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Run not found")

    payload = [
        {
            "id": str(step.id),
            "run_id": str(step.run_id),
            "step_key": step.step_key,
            "step_order": step.step_order,
            "status": step.status,
            "attempt_count": step.attempt_count,
            "max_attempts": step.max_attempts,
            "next_retry_at": step.next_retry_at.isoformat() if step.next_retry_at else None,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "finished_at": step.finished_at.isoformat() if step.finished_at else None,
            "last_error": step.last_error,
        }
        for step in steps
    ]
    return JSONResponse(content=payload)

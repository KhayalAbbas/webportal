"""
Company Research routes for UI.
"""

from typing import Optional
from uuid import UUID
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Query, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.role import Role
from app.models.company import Company
from app.services.company_research_service import CompanyResearchService
from app.services.company_extraction_service import CompanyExtractionService
from app.services.ai_proposal_service import AIProposalService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyProspectCreate,
    CompanyProspectUpdateManual,
    SourceDocumentCreate,
)
from app.schemas.ai_proposal import AIProposal


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/company-research", response_class=HTMLResponse)
async def company_research_list(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    role_id: Optional[str] = Query(None),
):
    """
    Company Research main page - shows runs grouped by role/mandate.
    """
    # Get available roles for filter dropdown
    roles_query = (
        select(Role, Company.name.label("company_name"))
        .join(Company, Company.id == Role.company_id)
        .where(Role.tenant_id == current_user.tenant_id)
        .order_by(Company.name, Role.title)
        .limit(200)
    )
    roles_result = await session.execute(roles_query)
    available_roles = [
        {"id": str(row.Role.id), "title": row.Role.title, "company_name": row.company_name}
        for row in roles_result.all()
    ]
    
    # If a role is selected, show runs for that role
    runs = []
    selected_role = None
    if role_id:
        try:
            role_uuid = UUID(role_id)
            
            # Get role details
            role_query = (
                select(Role, Company.name.label("company_name"))
                .join(Company, Company.id == Role.company_id)
                .where(Role.id == role_uuid, Role.tenant_id == current_user.tenant_id)
            )
            role_result = await session.execute(role_query)
            role_row = role_result.first()
            
            if role_row:
                selected_role = {
                    "id": str(role_row.Role.id),
                    "title": role_row.Role.title,
                    "company_name": role_row.company_name,
                }
                
                # Get research runs for this role
                service = CompanyResearchService(session)
                runs_list = await service.list_research_runs_for_role(
                    tenant_id=current_user.tenant_id,
                    role_mandate_id=role_uuid,
                    limit=50,
                )
                
                # Convert to dict with prospect count
                for run in runs_list:
                    prospect_count = await service.count_prospects_for_run(
                        current_user.tenant_id, run.id
                    )
                    runs.append({
                        "id": str(run.id),
                        "name": run.name,
                        "description": run.description,
                        "status": run.status,
                        "created_at": run.created_at,
                        "prospect_count": prospect_count,
                    })
        except ValueError:
            pass
    
    return templates.TemplateResponse(
        "company_research_list.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "company_research",
            "available_roles": available_roles,
            "selected_role": selected_role,
            "runs": runs,
            "role_id": role_id,
        }
    )


@router.post("/ui/company-research/runs/create")
async def create_research_run(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    role_mandate_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    sector: str = Form(""),
    region_scope: str = Form(""),  # Comma-separated
    primary_metric: str = Form("total_assets"),
    currency: str = Form("USD"),
    as_of_year: int = Form(2024),
    direction: str = Form("desc"),
):
    """
    Create a new company research run.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    try:
        role_uuid = UUID(role_mandate_id)
        
        # Parse region scope
        regions = [r.strip().upper() for r in region_scope.split(",") if r.strip()]
        
        # Build config
        config = {
            "ranking": {
                "primary_metric": primary_metric,
                "currency": currency,
                "as_of_year": as_of_year,
                "direction": direction,
                "fallback_years_back": 2
            },
            "enrichment": {
                "metrics_to_collect": [primary_metric]
            }
        }
        
        # Create run
        service = CompanyResearchService(session)
        run_create = CompanyResearchRunCreate(
            role_mandate_id=role_uuid,
            name=name,
            description=description if description else None,
            sector=sector if sector else "general",  # Required field
            region_scope=regions if regions else None,
            config=config,
            status="active",
        )
        
        run = await service.create_research_run(
            tenant_id=str(current_user.tenant_id),
            data=run_create,
            created_by_user_id=current_user.user_id,  # Already a UUID
        )
        
        await session.commit()
        
        # Redirect to the run detail page
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run.id}",
            status_code=303
        )
    
    except Exception as e:
        # Redirect back with error
        return RedirectResponse(
            url=f"/ui/company-research?role_id={role_mandate_id}&error=Failed to create run: {str(e)}",
            status_code=303
        )


@router.get("/ui/company-research/runs/{run_id}", response_class=HTMLResponse)
async def company_research_run_detail(
    request: Request,
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    order_by: str = Query("manual"),  # Default to manual ordering
    success_message: Optional[str] = Query(None),
    error_message: Optional[str] = Query(None),
):
    """
    Company Research Run detail page - shows prospects with sorting.
    """
    service = CompanyResearchService(session)
    
    # Get run
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Get role details
    role_query = (
        select(Role, Company.name.label("company_name"))
        .join(Company, Company.id == Role.company_id)
        .where(Role.id == run.role_mandate_id, Role.tenant_id == current_user.tenant_id)
    )
    role_result = await session.execute(role_query)
    role_row = role_result.first()
    
    role_info = None
    if role_row:
        role_info = {
            "id": str(role_row.Role.id),
            "title": role_row.Role.title,
            "company_name": role_row.company_name,
        }
    
    # Get prospects with selected ordering
    prospects_list = await service.list_prospects_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
        order_by=order_by,
        limit=200,
    )
    
    # Fetch evidence for each prospect to show counts and sources
    from app.models.company_research import CompanyProspectEvidence, CompanyMetric
    
    # Get all available metric keys for this run (for dynamic sorting dropdown)
    metrics_keys_query = select(CompanyMetric.metric_key).where(
        CompanyMetric.tenant_id == current_user.tenant_id,
        CompanyMetric.company_research_run_id == run_id,
    ).distinct()
    metrics_keys_result = await session.execute(metrics_keys_query)
    available_metrics = sorted([row[0] for row in metrics_keys_result])
    
    prospects = []
    for prospect in prospects_list:
        # Get evidence for this prospect
        evidence_query = select(CompanyProspectEvidence).where(
            CompanyProspectEvidence.tenant_id == current_user.tenant_id,
            CompanyProspectEvidence.company_prospect_id == prospect.id,
        )
        evidence_result = await session.execute(evidence_query)
        evidence_list = evidence_result.scalars().all()
        
        # Collect list sources
        list_sources = set()
        for ev in evidence_list:
            if ev.source_type == "manual_list" and ev.source_name:
                # Extract just "A" or "B" from "List A" or "List B"
                if "A" in ev.source_name:
                    list_sources.add("A")
                elif "B" in ev.source_name:
                    list_sources.add("B")
        
        # Get all metrics for this prospect (we'll display them dynamically)
        all_metrics_query = select(CompanyMetric).where(
            CompanyMetric.tenant_id == current_user.tenant_id,
            CompanyMetric.company_prospect_id == prospect.id,
        ).order_by(CompanyMetric.metric_key, CompanyMetric.as_of_date.desc().nullslast())
        
        all_metrics_result = await session.execute(all_metrics_query)
        all_metrics = all_metrics_result.scalars().all()
        
        # Build metrics dict for easy access
        metrics_dict = {}
        for metric in all_metrics:
            if metric.metric_key not in metrics_dict:
                # Format the metric value based on type
                if metric.value_type == "number" and metric.value_number is not None:
                    value = metric.value_number
                    currency = metric.value_currency or ""
                    unit = metric.unit or ""
                    # Format large numbers with B/M suffixes
                    if value >= 1_000_000_000:
                        metrics_dict[metric.metric_key] = f"{currency} {value/1_000_000_000:.1f}B{unit}"
                    elif value >= 1_000_000:
                        metrics_dict[metric.metric_key] = f"{currency} {value/1_000_000:.1f}M{unit}"
                    else:
                        metrics_dict[metric.metric_key] = f"{currency} {value:,.0f}{unit}"
                elif metric.value_type == "text" and metric.value_text is not None:
                    metrics_dict[metric.metric_key] = metric.value_text
                elif metric.value_type == "bool" and metric.value_bool is not None:
                    metrics_dict[metric.metric_key] = "✓" if metric.value_bool else "✗"
                elif metric.value_type == "json" and metric.value_json is not None:
                    import json
                    metrics_dict[metric.metric_key] = json.dumps(metric.value_json)[:50] + "..."
        
        prospects.append({
            "id": str(prospect.id),
            "name_raw": prospect.name_raw,
            "name_normalized": prospect.name_normalized,
            "website_url": prospect.website_url,
            "hq_city": prospect.hq_city,
            "hq_country": prospect.hq_country,
            "sector": prospect.sector,
            "description": prospect.description,
            "relevance_score": prospect.relevance_score,
            "evidence_score": prospect.evidence_score,
            "manual_priority": prospect.manual_priority,
            "is_pinned": prospect.is_pinned,
            "status": prospect.status,
            "evidence_count": len(evidence_list),
            "list_sources": ", ".join(sorted(list_sources)) if list_sources else "-",
            "ai_rank": prospect.ai_rank,
            "ai_score": prospect.ai_score,
            "metrics": metrics_dict,  # All metrics for this prospect
        })
    
    # Get sources for this run (Phase 2A)
    sources_list = await service.list_sources_for_run(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
    )
    
    sources = []
    for source in sources_list:
        sources.append({
            "id": str(source.id),
            "source_type": source.source_type,
            "title": source.title,
            "url": source.url,
            "status": source.status,
            "created_at": source.created_at,
        })
    
    # Extract selected metric key from order_by (e.g., "metric:fleet_size" -> "fleet_size")
    selected_metric_key = None
    if order_by.startswith("metric:"):
        selected_metric_key = order_by.split(":", 1)[1]
    
    return templates.TemplateResponse(
        "company_research_run_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "company_research",
            "run": {
                "id": str(run.id),
                "name": run.name,
                "description": run.description,
                "status": run.status,
                "config": run.config,
                "created_at": run.created_at,
            },
            "role_info": role_info,
            "prospects": prospects,
            "sources": sources,
            "available_metrics": available_metrics,
            "selected_metric_key": selected_metric_key,
            "order_by": order_by,
            "success_message": success_message,
            "error_message": error_message,
        }
    )


@router.post("/ui/company-research/prospects/{prospect_id}/update-manual")
async def update_prospect_manual_ui(
    prospect_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    manual_priority: Optional[str] = Form(None),
    manual_notes: Optional[str] = Form(None),
    is_pinned: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    run_id: str = Form(...),
):
    """
    Update manual fields for a prospect (called from inline editing).
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    service = CompanyResearchService(session)
    
    # Parse manual_priority (empty string = None)
    priority_value = None
    if manual_priority and manual_priority.strip():
        try:
            priority_value = int(manual_priority)
        except ValueError:
            pass
    
    # Parse is_pinned
    pinned_value = is_pinned == "true" or is_pinned == "on"
    
    # Build update data
    update_data = CompanyProspectUpdateManual(
        manual_priority=priority_value,
        manual_notes=manual_notes if manual_notes else None,
        is_pinned=pinned_value,
        status=status if status else "new",
    )
    
    # Update prospect
    prospect = await service.update_prospect_manual_fields(
        tenant_id=current_user.tenant_id,
        prospect_id=prospect_id,
        data=update_data,
    )
    
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    
    await session.commit()
    
    # Redirect back to run detail
    return RedirectResponse(
        url=f"/ui/company-research/runs/{run_id}?success_message=Updated",
        status_code=303
    )


@router.post("/ui/company-research/runs/{run_id}/seed-dummy")
async def seed_dummy_prospects_ui(
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    [DEV ONLY] Create 5 dummy prospects for testing.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    service = CompanyResearchService(session)
    
    # Verify run exists
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Create 5 dummy prospects
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
    
    for data in dummy_data:
        prospect_create = CompanyProspectCreate(
            company_research_run_id=run_id,
            role_mandate_id=run.role_mandate_id,
            name_raw=data["name"],
            name_normalized=data["name"].lower().replace("ltd", "").replace(".", "").strip(),
            website_url=data["website"],
            hq_country=data["country_code"],
            hq_city=data["headquarters_location"].split(",")[0].strip() if "," in data["headquarters_location"] else data["headquarters_location"],
            sector=data["industry_sector"],
            description=data["brief_description"],
            relevance_score=data["relevance_score"],
            evidence_score=data["evidence_score"],
            manual_priority=data["manual_priority"],
            is_pinned=data["is_pinned"],
            status="new",
        )
        
        await service.create_prospect(
            tenant_id=current_user.tenant_id,
            data=prospect_create,
        )
    
    await session.commit()
    
    # Redirect back to run detail
    return RedirectResponse(
        url=f"/ui/company-research/runs/{run_id}?success_message=Created 5 dummy prospects",
        status_code=303
    )


# ============================================================================
# Source Management Routes (Phase 2A)
# ============================================================================

@router.post("/ui/company-research/runs/{run_id}/sources/add-url", response_class=HTMLResponse)
async def add_source_url(
    run_id: UUID,
    url: str = Form(...),
    title: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """Add a URL source to a research run."""
    service = CompanyResearchService(session)
    
    # Verify run exists and user has access
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Create source document
    await service.add_source(
        tenant_id=current_user.tenant_id,
        data=SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="url",
            title=title or url,
            url=url,
        ),
    )
    
    await session.commit()
    
    return RedirectResponse(
        url=f"/ui/company-research/runs/{run_id}?success_message=URL source added",
        status_code=303
    )


@router.post("/ui/company-research/runs/{run_id}/sources/add-text", response_class=HTMLResponse)
async def add_source_text(
    run_id: UUID,
    content: str = Form(...),
    title: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """Add a text source to a research run."""
    try:
        service = CompanyResearchService(session)
        
        # Verify run exists and user has access
        run = await service.get_research_run(current_user.tenant_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Research run not found")
        
        # Create source document
        await service.add_source(
            tenant_id=current_user.tenant_id,
            data=SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="text",
                title=title or "Text source",
                content_text=content,
            ),
        )
        
        await session.commit()
        
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?success_message=Text source added",
            status_code=303
        )
    except Exception as e:
        await session.rollback()
        # Log the error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error adding text source: {str(e)}", exc_info=True)
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?error_message=Failed to add source: {str(e)}",
            status_code=303
        )


@router.post("/ui/company-research/runs/{run_id}/sources/process", response_class=HTMLResponse)
async def process_sources(
    run_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """Process all pending sources for a research run."""
    service = CompanyResearchService(session)
    extraction_service = CompanyExtractionService(session)
    
    # Verify run exists and user has access
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Process sources
    result = await extraction_service.process_sources(
        tenant_id=current_user.tenant_id,
        run_id=run_id,
    )
    
    await session.commit()
    
    # Build success message with detailed stats
    msg = f"Processed {result['processed']} sources. "
    msg += f"Found {result['companies_found']} companies. "
    msg += f"{result['companies_new']} new, {result['companies_existing']} existing."
    
    # Add per-source details if available
    if result.get('sources_detail'):
        msg += "<br><br><strong>Details:</strong><br>"
        for detail in result['sources_detail']:
            msg += f"• {detail['title']} | chars: {detail['chars']} | lines: {detail['lines']} | "
            msg += f"extracted: {detail['extracted']} | new: {detail['new']} | existing: {detail['existing']}<br>"
    
    return RedirectResponse(
        url=f"/ui/company-research/runs/{run_id}?success_message={msg}",
        status_code=303
    )

@router.post("/ui/company-research/runs/{run_id}/ingest-lists", response_class=HTMLResponse)
async def ingest_manual_lists(
    run_id: UUID,
    list_a: str = Form(""),
    list_b: str = Form(""),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Phase 1: Manual List Ingestion
    Parse two newline-separated lists of company names.
    Normalize, deduplicate, and create CompanyProspect records with evidence tracking.
    """
    service = CompanyResearchService(session)
    
    # Verify run exists and user has access
    run = await service.get_research_run(current_user.tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    
    # Parse and normalize both lists
    def parse_list(text: str, source_name: str):
        """Parse newline-separated names, normalize, track originals."""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        normalized = []
        for line in lines:
            norm = _normalize_company_name(line)
            if norm:  # Skip empty after normalization
                normalized.append({
                    'raw': line,
                    'normalized': norm,
                    'source': source_name
                })
        return normalized
    
    list_a_entries = parse_list(list_a, "List A")
    list_b_entries = parse_list(list_b, "List B")
    all_entries = list_a_entries + list_b_entries
    
    # Statistics tracking
    stats = {
        'parsed_total': len(all_entries),
        'parsed_a': len(list_a_entries),
        'parsed_b': len(list_b_entries),
        'new': 0,
        'existing': 0,
        'duplicates': 0,
    }
    
    # Group by normalized name to detect duplicates within submission
    from collections import defaultdict
    entries_by_norm = defaultdict(list)
    for entry in all_entries:
        entries_by_norm[entry['normalized']].append(entry)
    
    # Process each unique normalized name
    for norm_name, entries in entries_by_norm.items():
        # Check if prospect already exists in this run
        from app.models.company_research import CompanyProspect, CompanyProspectEvidence
        existing = await session.execute(
            select(CompanyProspect).where(
                CompanyProspect.tenant_id == current_user.tenant_id,
                CompanyProspect.company_research_run_id == run_id,
                CompanyProspect.name_normalized == norm_name,
            )
        )
        prospect = existing.scalar_one_or_none()
        
        if prospect:
            # Existing prospect - just add new evidence
            stats['existing'] += 1
            
            # Add evidence for each source (dedupe by source)
            sources_seen = set()
            for entry in entries:
                if entry['source'] not in sources_seen:
                    evidence = CompanyProspectEvidence(
                        tenant_id=current_user.tenant_id,
                        company_prospect_id=prospect.id,
                        source_type="manual_list",
                        source_name=entry['source'],
                        raw_snippet=entry['raw'],
                    )
                    session.add(evidence)
                    sources_seen.add(entry['source'])
        else:
            # New prospect - create with evidence
            stats['new'] += 1
            
            # Use first entry as primary raw name
            primary_entry = entries[0]
            prospect = CompanyProspect(
                tenant_id=current_user.tenant_id,
                company_research_run_id=run_id,
                role_mandate_id=run.role_mandate_id,
                name_raw=primary_entry['raw'],
                name_normalized=norm_name,
                status='new',
            )
            session.add(prospect)
            await session.flush()  # Get prospect.id
            
            # Add evidence for each source (dedupe by source)
            sources_seen = set()
            for entry in entries:
                if entry['source'] not in sources_seen:
                    evidence = CompanyProspectEvidence(
                        tenant_id=current_user.tenant_id,
                        company_prospect_id=prospect.id,
                        source_type="manual_list",
                        source_name=entry['source'],
                        raw_snippet=entry['raw'],
                    )
                    session.add(evidence)
                    sources_seen.add(entry['source'])
        
        # Count duplicates within submission (multiple entries with same normalized name)
        if len(entries) > 1:
            stats['duplicates'] += len(entries) - 1
    
    await session.commit()
    
    # Build success message
    msg = f"✅ Parsed {stats['parsed_total']} lines "
    msg += f"(List A: {stats['parsed_a']}, List B: {stats['parsed_b']}). "
    msg += f"Accepted {len(entries_by_norm)} unique companies: "
    msg += f"{stats['new']} new, {stats['existing']} existing"
    if stats['duplicates'] > 0:
        msg += f", {stats['duplicates']} duplicates within submission"
    msg += "."
    
    return RedirectResponse(
        url=f"/ui/company-research/runs/{run_id}?success_message={msg}",
        status_code=303
    )


def _normalize_company_name(name: str) -> str:
    """
    Normalize company name for canonical identity matching.
    Strips legal suffixes, normalizes whitespace, lowercases.
    """
    if not name:
        return ""
    
    normalized = name.lower().strip()
    
    # Remove trailing punctuation first
    while normalized and normalized[-1] in '.,;:':
        normalized = normalized[:-1].strip()
    
    # Remove common legal suffixes (iterate to handle multiple)
    suffixes = [
        ' ltd', ' llc', ' plc', ' saog', ' sa', ' gmbh', ' ag',
        ' inc', ' corp', ' corporation', ' limited', ' group', ' holdings',
        ' company', ' co',
    ]
    
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                changed = True
                break
        # Remove trailing punctuation after each suffix removal
        while normalized and normalized[-1] in '.,;:':
            normalized = normalized[:-1].strip()
            changed = True
    
    # Normalize whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized.strip()

# Phase 2: AI Proposal endpoints added here - see continuation

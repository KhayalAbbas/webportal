from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.core.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.research_event import ResearchEvent
from app.models.source_document import SourceDocument
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.models.research_run import ResearchRun
from app.models.candidate import Candidate
from app.models.company import Company

router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/research")
async def research_page(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Research activity overview page"""
    
    # Get recent research events
    query = (
        select(ResearchEvent)
        .where(ResearchEvent.tenant_id == current_user.tenant_id)
        .order_by(
            ResearchEvent.created_at.desc()
        )
        .limit(10)
    )
    result = await db.execute(query)
    research_events = result.scalars().all()
    
    # Resolve entity names for research events
    for event in research_events:
        event.entity_name = None
        if event.entity_id and event.entity_type:
            if event.entity_type == "CANDIDATE":
                result = await db.execute(
                    select(Candidate).where(
                        Candidate.id == event.entity_id,
                        Candidate.tenant_id == current_user.tenant_id
                    )
                )
                candidate = result.scalar_one_or_none()
                if candidate:
                    event.entity_name = f"{candidate.first_name} {candidate.last_name}"
            elif event.entity_type == "COMPANY":
                result = await db.execute(
                    select(Company).where(
                        Company.id == event.entity_id,
                        Company.tenant_id == current_user.tenant_id
                    )
                )
                company = result.scalar_one_or_none()
                if company:
                    event.entity_name = company.name
    
    # Get recent source documents
    query = (
        select(SourceDocument)
        .where(SourceDocument.tenant_id == current_user.tenant_id)
        .order_by(SourceDocument.created_at.desc())
        .limit(10)
    )
    result = await db.execute(query)
    source_documents = result.scalars().all()
    
    # Source documents don't have entity names - they have research_event_id
    # We won't resolve names for source_documents to keep it simple
    
    # Get recent AI enrichments
    query = (
        select(AIEnrichmentRecord)
        .where(AIEnrichmentRecord.tenant_id == current_user.tenant_id)
        .order_by(AIEnrichmentRecord.created_at.desc())
        .limit(10)
    )
    result = await db.execute(query)
    ai_enrichments = result.scalars().all()
    
    # Get recent Phase 3 research runs
    query = (
        select(ResearchRun)
        .where(ResearchRun.tenant_id == current_user.tenant_id)
        .order_by(ResearchRun.created_at.desc())
        .limit(10)
    )
    result = await db.execute(query)
    research_runs = result.scalars().all()
    
    # Resolve entity names for AI enrichments (using target_id/target_type)
    for enrichment in ai_enrichments:
        enrichment.entity_name = None
        if enrichment.target_id and enrichment.target_type:
            if enrichment.target_type == "CANDIDATE":
                result = await db.execute(
                    select(Candidate).where(
                        Candidate.id == enrichment.target_id,
                        Candidate.tenant_id == current_user.tenant_id
                    )
                )
                candidate = result.scalar_one_or_none()
                if candidate:
                    enrichment.entity_name = f"{candidate.first_name} {candidate.last_name}"
            elif enrichment.target_type == "COMPANY":
                result = await db.execute(
                    select(Company).where(
                        Company.id == enrichment.target_id,
                        Company.tenant_id == current_user.tenant_id
                    )
                )
                company = result.scalar_one_or_none()
                if company:
                    enrichment.entity_name = company.name
    
    return templates.TemplateResponse(
        "research.html",
        {
            "request": request,
            "current_user": current_user,
            "research_events": research_events,
            "source_documents": source_documents,
            "ai_enrichments": ai_enrichments,
            "research_runs": research_runs
        }
    )


@router.get("/ui/research/runs/{run_id}/steps")
async def research_run_steps(
    request: Request,
    run_id: str,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Proxy to research run steps API with session authentication"""
    from app.services.research_run_service import ResearchRunService
    from uuid import UUID
    
    try:
        service = ResearchRunService(db)
        steps = await service.list_steps(current_user.tenant_id, UUID(run_id))
        
        # Convert to JSON response
        from fastapi.responses import JSONResponse
        steps_data = []
        for step in steps:
            steps_data.append({
                "id": str(step.id),
                "run_id": str(step.run_id),
                "step_key": step.step_key,
                "step_type": step.step_type,
                "status": step.status,
                "inputs_json": step.inputs_json,
                "outputs_json": step.outputs_json,
                "provider_meta": step.provider_meta,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                "output_sha256": step.output_sha256,
                "error": step.error,
                "created_at": step.created_at.isoformat() if step.created_at else None,
                "updated_at": step.updated_at.isoformat() if step.updated_at else None
            })
        
        return JSONResponse(content=steps_data)
        
    except ValueError as e:
        if str(e) == "run_not_found":
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

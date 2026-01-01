"""
Phase 2: AI Proposal endpoints for Company Research.

These endpoints handle validation and ingestion of AI-generated proposals.
"""

from typing import Optional
from uuid import UUID
import json

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from app.core.dependencies import get_db
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.services.ai_proposal_service import AIProposalService
from app.services.company_research_service import CompanyResearchService
from app.schemas.company_research import SourceDocumentCreate
from app.schemas.ai_proposal import AIProposal


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.post("/ui/company-research/runs/{run_id}/validate-proposal")
async def validate_ai_proposal(
    run_id: UUID,
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Phase 2: Validate AI Proposal JSON
    Returns validation errors without making changes.
    """
    # Get form data
    form = await request.form()
    proposal_json = form.get("proposal_json", "")
    
    if not proposal_json:
        return {"success": False, "errors": ["No JSON provided"]}
    
    try:
        # Parse JSON
        proposal_data = json.loads(proposal_json)
        
        # Validate against schema
        proposal = AIProposal(**proposal_data)
        
        # Business validation
        service = AIProposalService(session)
        validation_result = await service.validate_proposal(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            proposal=proposal,
        )
        
        return JSONResponse({
            "success": validation_result.valid,
            "errors": [f"{e.field}: {e.message}" for e in validation_result.errors],
            "warnings": validation_result.warnings,
            "company_count": validation_result.company_count,
            "source_count": validation_result.source_count,
            "metric_count": validation_result.metric_count,
        })
        
    except json.JSONDecodeError as e:
        return JSONResponse({"success": False, "errors": [f"Invalid JSON: {str(e)}"]})
    except ValidationError as e:
        errors = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error['loc'])
            errors.append(f"{field}: {error['msg']}")
        return JSONResponse({"success": False, "errors": errors})
    except Exception as e:
        return JSONResponse({"success": False, "errors": [f"Validation error: {str(e)}"]})


@router.post("/ui/company-research/runs/{run_id}/ingest-proposal")
async def ingest_ai_proposal(
    run_id: UUID,
    proposal_json: str = Form(...),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Phase 2: Ingest AI Proposal JSON
    Parses and stores companies, metrics, aliases, and evidence.
    """
    try:
        # Parse JSON
        proposal_data = json.loads(proposal_json)
        
        # Validate against schema (early feedback)
        _ = AIProposal(**proposal_data)

        research_service = CompanyResearchService(session)
        source_payload = SourceDocumentCreate(
            company_research_run_id=run_id,
            source_type="ai_proposal",
            title="AI Proposal submission",
            content_text=proposal_json,
            meta={"kind": "proposal", "submitted_via": "ui_form"},
        )
        await research_service.add_source(current_user.tenant_id, source_payload)
        summary = await research_service.ingest_proposal_sources(current_user.tenant_id, run_id)
        await session.commit()

        if summary.get("ingestions_failed", 0) == 0:
            msg = (
                f"✅ AI Proposal ingested | sources {summary.get('processed_sources', 0)}; "
                f"companies new {summary.get('companies_new', 0)}, existing {summary.get('companies_existing', 0)}"
            )
            return RedirectResponse(
                url=f"/ui/company-research/runs/{run_id}?success_message={msg}",
                status_code=303,
            )

        error_msg = "❌ Ingestion failed"
        if summary.get("details"):
            errors = summary["details"][0].get("errors") or []
            if errors:
                error_msg += f": {'; '.join(errors[:3])}"
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?error_message={error_msg}",
            status_code=303,
        )
        
    except json.JSONDecodeError as e:
        error_msg = f"❌ Invalid JSON: {str(e)}"
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?error_message={error_msg}",
            status_code=303
        )
    except ValidationError as e:
        errors = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error['loc'])
            errors.append(f"{field}: {error['msg']}")
        error_msg = "❌ Validation failed: " + "; ".join(errors[:3])
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?error_message={error_msg}",
            status_code=303
        )
    except Exception as e:
        error_msg = f"❌ Ingestion error: {str(e)}"
        return RedirectResponse(
            url=f"/ui/company-research/runs/{run_id}?error_message={error_msg}",
            status_code=303
        )

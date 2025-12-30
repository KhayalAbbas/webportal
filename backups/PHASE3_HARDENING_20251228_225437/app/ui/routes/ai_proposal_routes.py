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
        
        # Validate against schema
        proposal = AIProposal(**proposal_data)
        
        # Ingest
        service = AIProposalService(session)
        ingestion_result = await service.ingest_proposal(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
            proposal=proposal,
        )
        
        if ingestion_result.success:
            # Build success message
            msg = f"✅ AI Proposal Ingested! "
            msg += f"Companies: {ingestion_result.companies_ingested} "
            msg += f"({ingestion_result.companies_new} new, {ingestion_result.companies_existing} updated). "
            msg += f"Metrics: {ingestion_result.metrics_ingested}. "
            msg += f"Aliases: {ingestion_result.aliases_ingested}. "
            msg += f"Sources: {ingestion_result.sources_created}."
            
            if ingestion_result.warnings:
                msg += f" ⚠️ Warnings: {'; '.join(ingestion_result.warnings[:3])}"
            
            return RedirectResponse(
                url=f"/ui/company-research/runs/{run_id}?success_message={msg}",
                status_code=303
            )
        else:
            # Build error message
            error_msg = "❌ Ingestion failed: " + "; ".join(ingestion_result.errors[:5])
            return RedirectResponse(
                url=f"/ui/company-research/runs/{run_id}?error_message={error_msg}",
                status_code=303
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

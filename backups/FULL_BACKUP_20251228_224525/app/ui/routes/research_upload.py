"""
Phase 3 Bundle Upload routes for UI.
"""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.services.research_run_service import ResearchRunService
from app.schemas.research_run import ResearchRunCreate, RunBundleV1

router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/research/upload", response_class=HTMLResponse)
async def research_upload_form(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    """Render the Phase 3 bundle upload form."""
    return templates.TemplateResponse(
        "research_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "research_upload"
        }
    )


@router.post("/ui/research/upload", response_class=HTMLResponse)
async def research_upload_submit(
    request: Request,
    objective: Annotated[str, Form()],
    bundle_file: UploadFile = File(...),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Handle the Phase 3 bundle upload form submission."""
    
    try:
        # Validate file type
        if not bundle_file.filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="File must be a JSON file")
        
        # Read and parse uploaded JSON
        content = await bundle_file.read()
        try:
            bundle_data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
        
        # Create research run
        research_service = ResearchRunService(db)
        
        run_create = ResearchRunCreate(
            objective=objective,
            constraints={},
            rank_spec={},
            idempotency_key=f"ui_upload_{objective[:50]}".replace(" ", "_")
        )
        
        research_run = await research_service.create_run(
            current_user.tenant_id,
            run_create,
            current_user.user_id
        )
        
        # Force bundle run_id to match created run
        bundle_data["run_id"] = str(research_run.id)
        
        # Validate and upload bundle
        try:
            bundle_schema = RunBundleV1(**bundle_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Bundle validation failed: {str(e)}")
        
        # Upload bundle using service
        upload_result, already_accepted = await research_service.accept_bundle(
            current_user.tenant_id,
            research_run.id,
            bundle_schema
        )
        
        # Render success page
        return templates.TemplateResponse(
            "research_upload_result.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "research_upload",
                "success": True,
                "run_id": str(research_run.id),
                "objective": objective,
                "upload_result": upload_result,
                "already_accepted": already_accepted
            }
        )
        
    except HTTPException as e:
        # Render error page
        return templates.TemplateResponse(
            "research_upload_result.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "research_upload",
                "success": False,
                "error": e.detail,
                "objective": objective if 'objective' in locals() else ""
            }
        )
    except Exception as e:
        # Render unexpected error page
        return templates.TemplateResponse(
            "research_upload_result.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "research_upload",
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "objective": objective if 'objective' in locals() else ""
            }
        )
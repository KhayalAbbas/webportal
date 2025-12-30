"""
Stub routes for UI pages not yet implemented.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


# Only Settings page remains as a stub
@router.get("/ui/settings", response_class=HTMLResponse)
async def settings_stub(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    return templates.TemplateResponse(
        "stub.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "settings",
            "page_name": "Settings",
        }
    )

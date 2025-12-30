"""
Authentication routes for UI.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.services.auth_service import AuthService
from app.ui.session import session_manager
from app.ui.dependencies import get_optional_ui_user


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user = Depends(get_optional_ui_user)
):
    """
    Display login form.
    
    If user is already logged in, redirect to dashboard.
    """
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "email": None,
            "tenant_id": None,
        }
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(...),
    session: AsyncSession = Depends(get_db),
):
    """
    Process login form submission.
    
    Validates credentials and creates session cookie on success.
    """
    try:
        tenant_uuid = UUID(tenant_id)
    except ValueError:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid tenant ID format",
                "email": email,
                "tenant_id": tenant_id,
            }
        )
    
    # Authenticate user
    auth_service = AuthService(session)
    user = await auth_service.authenticate_user(
        tenant_id=tenant_uuid,
        email=email,
        password=password
    )
    
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid email, password, or tenant ID",
                "email": email,
                "tenant_id": tenant_id,
            },
            status_code=401
        )
    
    # Create session token
    session_token = session_manager.create_session_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role
    )
    
    # Redirect to dashboard with session cookie
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        max_age=60 * 60 * 8,  # 8 hours
        samesite="lax"
    )
    
    return response


@router.get("/logout")
async def logout():
    """
    Log out user by clearing session cookie.
    """
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session")
    return response

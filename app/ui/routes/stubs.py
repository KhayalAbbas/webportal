"""Settings routes (integrations)."""

from urllib.parse import quote
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.errors import AppError
from app.services.integration_settings_service import IntegrationSettingsService
from app.services.secrets_service import require_master_key
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


def _ensure_admin(user: UIUser) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def _error_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        code = exc.payload.get("error", {}).get("code")
        msg = exc.payload.get("error", {}).get("message", "An error occurred")
        return f"{code}: {msg}" if code else msg
    return str(exc)


@router.get("/ui/settings", response_class=HTMLResponse)
async def settings_root() -> RedirectResponse:
    return RedirectResponse(url="/ui/settings/integrations", status_code=303)


@router.get("/ui/settings/integrations", response_class=HTMLResponse)
async def settings_integrations(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
):
    _ensure_admin(current_user)
    service = IntegrationSettingsService(session)

    master_key_missing = False
    master_key_error = None
    try:
        require_master_key()
    except AppError as exc:
        master_key_missing = True
        master_key_error = _error_message(exc)

    state = await service.get_public_state(current_user.tenant_id)

    status_code = 400 if master_key_missing else 200

    return templates.TemplateResponse(
        "settings_integrations.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "settings",
            "active_settings_tab": "integrations",
            "state": state,
            "master_key_missing": master_key_missing,
            "master_key_error": master_key_error,
            "success_message": success_message,
            "error_message": error_message,
        },
        status_code=status_code,
    )


@router.get("/ui/settings/general", response_class=HTMLResponse)
async def settings_general(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    _ensure_admin(current_user)
    return templates.TemplateResponse(
        "settings_general.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "settings",
            "active_settings_tab": "general",
        },
        status_code=200,
    )


@router.post("/ui/settings/integrations/xai")
async def save_xai_settings(
    request: Request,
    api_key: str = Form(""),
    model: str = Form(""),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    _ensure_admin(current_user)
    service = IntegrationSettingsService(session)
    api_key_clean = api_key.strip()
    model_clean = model.strip()
    config_json = {"model": model_clean} if model_clean else {}

    try:
        require_master_key()
        await service.save_provider_settings(current_user.tenant_id, "xai_grok", api_key_clean or None, config_json, current_user.email)
        await session.commit()
        msg = quote("xAI settings saved")
        return RedirectResponse(url=f"/ui/settings/integrations?success_message={msg}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        msg = quote(_error_message(exc))
        return RedirectResponse(url=f"/ui/settings/integrations?error_message={msg}", status_code=303)


@router.post("/ui/settings/integrations/google")
async def save_google_settings(
    request: Request,
    api_key: str = Form(""),
    cx: str = Form(""),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    _ensure_admin(current_user)
    service = IntegrationSettingsService(session)
    api_key_clean = api_key.strip()
    cx_clean = cx.strip()
    config_json = {"cx": cx_clean} if cx_clean else {}

    try:
        require_master_key()
        await service.save_provider_settings(current_user.tenant_id, "google_cse", api_key_clean or None, config_json, current_user.email)
        await session.commit()
        msg = quote("Google CSE settings saved")
        return RedirectResponse(url=f"/ui/settings/integrations?success_message={msg}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        msg = quote(_error_message(exc))
        return RedirectResponse(url=f"/ui/settings/integrations?error_message={msg}", status_code=303)


@router.post("/ui/settings/integrations/xai/test")
async def test_xai(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    _ensure_admin(current_user)
    service = IntegrationSettingsService(session)
    try:
        require_master_key()
        result = await service.test_provider(current_user.tenant_id, "xai_grok", current_user.email)
        await session.commit()
        status_text = "Test passed" if result.get("status") == "pass" else "Test failed"
        msg = quote(status_text)
        return RedirectResponse(url=f"/ui/settings/integrations?success_message={msg}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        msg = quote(_error_message(exc))
        return RedirectResponse(url=f"/ui/settings/integrations?error_message={msg}", status_code=303)


@router.post("/ui/settings/integrations/google/test")
async def test_google(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    _ensure_admin(current_user)
    service = IntegrationSettingsService(session)
    try:
        require_master_key()
        result = await service.test_provider(current_user.tenant_id, "google_cse", current_user.email)
        await session.commit()
        status_text = "Test passed" if result.get("status") == "pass" else "Test failed"
        msg = quote(status_text)
        return RedirectResponse(url=f"/ui/settings/integrations?success_message={msg}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        msg = quote(_error_message(exc))
        return RedirectResponse(url=f"/ui/settings/integrations?error_message={msg}", status_code=303)

"""
UI dependencies for authentication and session management.
"""

from typing import Optional
from uuid import UUID

from fastapi import Cookie, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.ui.session import session_manager
from app.models.user import User
from app.repositories.user_repository import UserRepository


class UIUser:
    """Represents the current UI user from session."""
    
    def __init__(self, user_id: UUID, tenant_id: UUID, email: str, role: str):
        self.id = user_id
        self.user_id = user_id
        self.tenant_id = tenant_id  # Keep as UUID - models now match
        self.email = email
        self.role = role


async def get_current_ui_user_and_tenant(
    session_token: Optional[str] = Cookie(None, alias="session"),
) -> UIUser:
    """
    Get current user from session cookie.
    
    If session is invalid or missing, raises HTTPException with redirect.
    Use this dependency in all UI routes that require authentication.
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/login"}
        )
    
    session_data = session_manager.verify_session_token(session_token)
    
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Session expired",
            headers={"Location": "/login"}
        )
    
    return UIUser(
        user_id=UUID(session_data["user_id"]),
        tenant_id=UUID(session_data["tenant_id"]),
        email=session_data["email"],
        role=session_data["role"],
    )


async def get_optional_ui_user(
    session_token: Optional[str] = Cookie(None, alias="session"),
) -> Optional[UIUser]:
    """
    Get current user from session cookie, or None if not authenticated.
    
    Use this for pages like login where we want to check if already logged in.
    """
    if not session_token:
        return None
    
    session_data = session_manager.verify_session_token(session_token)
    
    if not session_data:
        return None
    
    return UIUser(
        user_id=UUID(session_data["user_id"]),
        tenant_id=UUID(session_data["tenant_id"]),
        email=session_data["email"],
        role=session_data["role"],
    )

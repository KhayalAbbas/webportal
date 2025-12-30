"""
Role-based permission helpers for the ATS system.

Defines roles and provides dependency functions to enforce permissions.
"""

from typing import List
from fastapi import HTTPException, status


# Define role hierarchy
class Roles:
    """Standard roles in the ATS system."""
    ADMIN = "admin"
    CONSULTANT = "consultant"
    BD_MANAGER = "bd_manager"
    VIEWER = "viewer"
    
    # All roles list for validation
    ALL = [ADMIN, CONSULTANT, BD_MANAGER, VIEWER]
    
    # Role capabilities matrix
    # admin: Full access to everything
    # consultant: Manage candidates, assignments, tasks, roles, companies
    # bd_manager: Manage BD opportunities, companies, contacts
    # viewer: Read-only access


def check_role_permission(user_role: str, allowed_roles: List[str]) -> bool:
    """
    Check if user's role is in the list of allowed roles.
    
    Args:
        user_role: The user's current role
        allowed_roles: List of roles that are permitted
        
    Returns:
        True if user has permission, False otherwise
    """
    if not user_role or not allowed_roles:
        return False
    return user_role in allowed_roles


def require_roles(allowed_roles: List[str]):
    """
    Dependency to require that current user has one of the allowed roles.
    
    Usage:
        @router.post("/candidates")
        async def create_candidate(
            current_user: UIUser = Depends(require_roles([Roles.ADMIN, Roles.CONSULTANT]))
        ):
            ...
    
    Args:
        allowed_roles: List of role names that are permitted
        
    Returns:
        Dependency function that checks permissions
        
    Raises:
        HTTPException: 403 if user doesn't have required role
    """
    def role_checker(user_role: str) -> None:
        if not check_role_permission(user_role, allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
    return role_checker


def require_admin():
    """
    Dependency to require admin role.
    
    Usage:
        @router.delete("/tenants/{tenant_id}")
        async def delete_tenant(
            _: None = Depends(require_admin())
        ):
            ...
    """
    def admin_checker(user_role: str) -> None:
        if user_role != Roles.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
    return admin_checker


# Permission check helpers for UI users
def check_can_write_candidates(user_role: str) -> bool:
    """Check if user can create/update candidates."""
    return user_role in [Roles.ADMIN, Roles.CONSULTANT]


def check_can_write_roles(user_role: str) -> bool:
    """Check if user can create/update roles."""
    return user_role in [Roles.ADMIN, Roles.CONSULTANT]


def check_can_write_companies(user_role: str) -> bool:
    """Check if user can create/update companies."""
    return user_role in [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER]


def check_can_write_bd(user_role: str) -> bool:
    """Check if user can create/update BD opportunities."""
    return user_role in [Roles.ADMIN, Roles.BD_MANAGER]


def check_can_write_tasks(user_role: str) -> bool:
    """Check if user can create/update tasks."""
    return user_role in [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER]


def check_can_write_lists(user_role: str) -> bool:
    """Check if user can create/update lists."""
    return user_role in [Roles.ADMIN, Roles.CONSULTANT]


def check_is_admin(user_role: str) -> bool:
    """Check if user is admin."""
    return user_role == Roles.ADMIN


def check_is_viewer_only(user_role: str) -> bool:
    """Check if user is viewer (read-only)."""
    return user_role == Roles.VIEWER


def raise_if_viewer(user_role: str, action: str = "perform this action") -> None:
    """
    Raise 403 error if user is viewer role.
    
    Args:
        user_role: User's role
        action: Description of action being blocked
        
    Raises:
        HTTPException: 403 if user is viewer
    """
    if check_is_viewer_only(user_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Viewers cannot {action}. Contact your administrator for write access."
        )


def raise_if_not_roles(user_role: str, allowed_roles: List[str], action: str = "perform this action") -> None:
    """
    Raise 403 error if user doesn't have one of the allowed roles.
    
    Args:
        user_role: User's role
        allowed_roles: List of permitted roles
        action: Description of action being blocked
        
    Raises:
        HTTPException: 403 if user doesn't have permission
    """
    if not check_role_permission(user_role, allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions to {action}. Required: {', '.join(allowed_roles)}"
        )

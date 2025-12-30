"""
FastAPI dependencies for the application.
"""

from typing import AsyncGenerator
from uuid import UUID
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.core.jwt import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

# Security scheme for JWT bearer tokens
security = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_tenant_id(x_tenant_id: str = Header(None)) -> str:
    """
    Extract and validate tenant_id from header.
    
    Raises 400 if X-Tenant-ID header is missing.
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required"
        )
    return x_tenant_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    Validates the JWT token, loads the user from database,
    and ensures the user is active.
    
    Raises:
        401: If token is invalid or user not found
        403: If user is not active
    """
    token = credentials.credentials
    
    # Decode JWT token
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Extract user_id from token
    user_id_str = payload.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Load user from database
    user_repository = UserRepository(db)
    user = await user_repository.get_by_id(UUID(user_id_str))
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    return user


async def verify_user_tenant_access(
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id)
) -> User:
    """
    Verify that the authenticated user belongs to the requested tenant.
    
    Args:
        user: Current authenticated user
        tenant_id: Tenant ID from X-Tenant-ID header
        
    Returns:
        User object if access is granted
        
    Raises:
        403: If user doesn't belong to the requested tenant
    """
    if str(user.tenant_id) != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not have access to tenant {tenant_id}"
        )
    
    return user


def require_role(*allowed_roles: str):
    """
    Dependency factory to require specific roles.
    
    Usage:
        @router.post("/", dependencies=[Depends(require_role("admin", "bd_manager"))])
        async def create_something(...):
            ...
    
    Args:
        allowed_roles: Tuple of allowed role names
        
    Returns:
        Dependency function that checks user role
    """
    async def check_role(user: User = Depends(verify_user_tenant_access)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}"
            )
        return user
    
    return check_role

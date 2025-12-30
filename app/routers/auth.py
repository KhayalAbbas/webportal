"""
Authentication router for login and user management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id, verify_user_tenant_access, require_role
from app.schemas.user import LoginRequest, LoginResponse, UserCreate, UserRead, UserUpdate
from app.services.auth_service import AuthService
from app.repositories.user_repository import UserRepository
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return JWT access token.
    
    Requires X-Tenant-ID header to identify the tenant.
    """
    auth_service = AuthService(db)
    result = await auth_service.login(tenant_id, credentials)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return result


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Create a new user in the system.
    
    Only admin users can create new users.
    The new user must belong to the same tenant as the admin.
    """
    # Ensure the new user is being created in the admin's tenant
    if user_data.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create users in other tenants"
        )
    
    user_repository = UserRepository(db)
    
    # Check if user already exists
    existing_user = await user_repository.get_by_email(user_data.tenant_id, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this tenant"
        )
    
    new_user = await user_repository.create(user_data)
    return new_user


@router.get("/users/me", response_model=UserRead)
async def get_current_user_info(
    current_user: User = Depends(verify_user_tenant_access)
):
    """
    Get information about the currently authenticated user.
    """
    return current_user


@router.get("/users", response_model=list[UserRead])
async def list_users(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    List all users in the current tenant.
    
    Only admin users can list all users.
    """
    if limit > 200:
        limit = 200
    
    user_repository = UserRepository(db)
    users = await user_repository.get_by_tenant(
        tenant_id=current_user.tenant_id,
        skip=skip,
        limit=limit
    )
    
    return users


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Update a user's information.
    
    Only admin users can update other users.
    """
    from uuid import UUID
    
    user_repository = UserRepository(db)
    user = await user_repository.get_by_id(UUID(user_id))
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Ensure the user being updated is in the same tenant
    if user.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update users in other tenants"
        )
    
    updated_user = await user_repository.update(user_id, user_data)
    return updated_user

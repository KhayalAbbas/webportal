"""
Authentication service for user login and token management.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import LoginRequest, LoginResponse, UserRead
from app.repositories.user_repository import UserRepository
from app.core.security import verify_password
from app.core.jwt import create_access_token


class AuthService:
    """Service for authentication operations."""
    
    def __init__(self, db: AsyncSession):
        self.user_repository = UserRepository(db)
    
    async def authenticate_user(
        self,
        tenant_id: UUID,
        email: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate a user by email and password.
        
        Args:
            tenant_id: Tenant ID to search within
            email: User email
            password: Plain text password
            
        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.user_repository.get_by_email(tenant_id, email)
        
        if not user:
            return None
        
        if not user.is_active:
            return None
        
        if not verify_password(password, user.hashed_password):
            return None
        
        return user
    
    def create_token_for_user(self, user: User) -> str:
        """
        Create a JWT access token for a user.
        
        Args:
            user: User object
            
        Returns:
            JWT token string
        """
        token_data = {
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "role": user.role,
        }
        return create_access_token(token_data)
    
    async def login(
        self,
        tenant_id: UUID,
        credentials: LoginRequest
    ) -> Optional[LoginResponse]:
        """
        Perform user login.
        
        Args:
            tenant_id: Tenant ID from header
            credentials: Login credentials
            
        Returns:
            LoginResponse with token and user data, or None if failed
        """
        user = await self.authenticate_user(
            tenant_id,
            credentials.email,
            credentials.password
        )
        
        if not user:
            return None
        
        access_token = self.create_token_for_user(user)
        
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserRead.model_validate(user)
        )

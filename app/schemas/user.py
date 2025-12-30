"""
User Pydantic schemas.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict


class UserCreate(BaseModel):
    """Schema for creating a new user."""
    
    tenant_id: UUID
    email: EmailStr
    full_name: str
    password: str
    role: str = "viewer"


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserRead(BaseModel):
    """Schema for reading user data (API response)."""
    
    id: UUID
    tenant_id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserRead):
    """Schema for user with hashed password (internal use)."""
    
    hashed_password: str


class LoginRequest(BaseModel):
    """Schema for login request."""
    
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Schema for login response."""
    
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class TokenData(BaseModel):
    """Schema for token payload data."""
    
    user_id: UUID
    tenant_id: UUID
    email: str
    role: str

"""
User repository - database operations for User.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import hash_password


class UserRepository:
    """Repository for User database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get a user by ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_email(self, tenant_id: UUID, email: str) -> Optional[User]:
        """Get a user by email within a tenant (case-insensitive email)."""
        if not email or not email.strip():
            return None
        email_clean = email.strip().lower()
        result = await self.db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                func.lower(User.email) == email_clean
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, data: UserCreate) -> User:
        """Create a new user."""
        user = User(
            tenant_id=data.tenant_id,
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user
    
    async def get_by_tenant(
        self,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50
    ) -> list[User]:
        """Get all users for a tenant."""
        result = await self.db.execute(
            select(User)
            .where(User.tenant_id == tenant_id)
            .order_by(User.full_name.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def update(self, user_id: UUID, data) -> User:
        """Update a user's information."""
        user = await self.get_by_id(user_id)
        if not user:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        
        # Hash password if it's being updated
        if "password" in update_data:
            update_data["hashed_password"] = hash_password(update_data.pop("password"))
        
        for field, value in update_data.items():
            setattr(user, field, value)
        
        await self.db.commit()
        await self.db.refresh(user)
        return user

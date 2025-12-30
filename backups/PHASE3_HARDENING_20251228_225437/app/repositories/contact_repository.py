"""
Contact repository - database operations for Contact.
"""

from typing import List, Optional
from uuid import UUID
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate


class ContactRepository:
    """Repository for Contact database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        company_id: Optional[UUID] = None,
        bd_status: Optional[str] = None,
        bd_owner: Optional[str] = None,
    ) -> List[Contact]:
        """List contacts for a tenant with filters."""
        query = select(Contact).where(Contact.tenant_id == tenant_id)
        
        if company_id is not None:
            query = query.where(Contact.company_id == company_id)
        if bd_status is not None:
            query = query.where(Contact.bd_status == bd_status)
        if bd_owner is not None:
            query = query.where(Contact.bd_owner == bd_owner)
        
        query = query.order_by(Contact.last_name.asc(), Contact.first_name.asc())
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, contact_id: UUID) -> Optional[Contact]:
        """Get a contact by ID for a specific tenant."""
        result = await self.db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: ContactCreate) -> Contact:
        """Create a new contact."""
        contact = Contact(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(contact)
        await self.db.flush()
        await self.db.refresh(contact)
        return contact
    
    async def update(
        self,
        tenant_id: str,
        contact_id: UUID,
        data: ContactUpdate
    ) -> Optional[Contact]:
        """Update a contact."""
        contact = await self.get_by_id(tenant_id, contact_id)
        if not contact:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(contact, field, value)
        
        contact.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(contact)
        return contact

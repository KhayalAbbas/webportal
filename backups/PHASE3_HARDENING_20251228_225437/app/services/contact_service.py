"""
Contact business logic service.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate
from app.repositories.contact_repository import ContactRepository


class ContactService:
    """Service for contact business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = ContactRepository(db)
    
    async def list_contacts(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        company_id: Optional[UUID] = None,
        bd_status: Optional[str] = None,
        bd_owner: Optional[str] = None,
    ) -> List[Contact]:
        """List contacts with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            company_id=company_id,
            bd_status=bd_status,
            bd_owner=bd_owner,
        )
    
    async def get_contact(self, tenant_id: str, contact_id: UUID) -> Optional[Contact]:
        """Get a contact by ID."""
        return await self.repository.get_by_id(tenant_id, contact_id)
    
    async def create_contact(self, tenant_id: str, data: ContactCreate) -> Contact:
        """Create a new contact."""
        return await self.repository.create(tenant_id, data)
    
    async def update_contact(
        self,
        tenant_id: str,
        contact_id: UUID,
        data: ContactUpdate
    ) -> Optional[Contact]:
        """Update a contact."""
        return await self.repository.update(tenant_id, contact_id, data)

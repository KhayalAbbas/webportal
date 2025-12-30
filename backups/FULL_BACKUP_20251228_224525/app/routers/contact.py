"""
Contact router - API endpoints for contacts.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services.contact_service import ContactService

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=List[ContactRead])
async def list_contacts(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    company_id: Optional[UUID] = None,
    bd_status: Optional[str] = None,
    bd_owner: Optional[str] = None,
):
    """
    List contacts with pagination and filters.
    
    Filters: company_id, bd_status, bd_owner.
    """
    service = ContactService(db)
    contacts = await service.list_contacts(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        company_id=company_id,
        bd_status=bd_status,
        bd_owner=bd_owner,
    )
    return contacts


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(
    contact_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a contact by ID."""
    service = ContactService(db)
    contact = await service.get_contact(tenant_id, contact_id)
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found for this tenant"
        )
    
    return contact


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(
    data: ContactCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new contact."""
    service = ContactService(db)
    contact = await service.create_contact(tenant_id, data)
    await db.commit()
    return contact


@router.put("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: UUID,
    data: ContactUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a contact."""
    service = ContactService(db)
    contact = await service.update_contact(tenant_id, contact_id, data)
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found for this tenant"
        )
    
    await db.commit()
    return contact

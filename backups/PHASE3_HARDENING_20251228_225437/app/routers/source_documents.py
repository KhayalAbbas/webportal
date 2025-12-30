"""
Source Documents router - store and retrieve research documents.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.source_document import SourceDocumentCreate, SourceDocumentRead, SourceDocumentUpdate
from app.services.source_document_service import SourceDocumentService

router = APIRouter(prefix="/source-documents", tags=["Source Documents"])


@router.get("/", response_model=list[SourceDocumentRead])
async def list_source_documents(
    current_user: User = Depends(verify_user_tenant_access),
    research_event_id: Optional[UUID] = Query(None, description="Filter by research event ID"),
    document_type: Optional[str] = Query(None, description="Filter by type: PDF, HTML, TEXT, TRANSCRIPT"),
    target_entity_type: Optional[str] = Query(None, description="Filter by target entity type"),
    target_entity_id: Optional[UUID] = Query(None, description="Filter by target entity ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List source documents with optional filters.
    
    All documents are scoped to the authenticated user's tenant.
    """
    service = SourceDocumentService(db)
    return await service.get_by_tenant(
        tenant_id=current_user.tenant_id,
        research_event_id=research_event_id,
        document_type=document_type,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        skip=skip,
        limit=limit
    )


@router.get("/{document_id}", response_model=SourceDocumentRead)
async def get_source_document(
    document_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific source document by ID.
    
    Only returns the document if it belongs to the user's tenant.
    """
    service = SourceDocumentService(db)
    document = await service.get_by_id(current_user.tenant_id, document_id)
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source document not found"
        )
    
    return document


@router.post("/", response_model=SourceDocumentRead, status_code=status.HTTP_201_CREATED)
async def create_source_document(
    document_data: SourceDocumentCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new source document.
    
    The document will be associated with the authenticated user's tenant.
    The research_event_id must belong to the same tenant.
    """
    service = SourceDocumentService(db)
    document = await service.create(current_user.tenant_id, document_data)
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research event not found or does not belong to your tenant"
        )
    
    return document


@router.patch("/{document_id}", response_model=SourceDocumentRead)
async def update_source_document(
    document_id: UUID,
    document_data: SourceDocumentUpdate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a source document.
    
    Only documents belonging to the user's tenant can be updated.
    """
    service = SourceDocumentService(db)
    updated_document = await service.update(current_user.tenant_id, document_id, document_data)
    
    if not updated_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source document not found"
        )
    
    return updated_document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_document(
    document_id: UUID,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a source document.
    
    Only documents belonging to the user's tenant can be deleted.
    """
    service = SourceDocumentService(db)
    deleted = await service.delete(current_user.tenant_id, document_id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source document not found"
        )

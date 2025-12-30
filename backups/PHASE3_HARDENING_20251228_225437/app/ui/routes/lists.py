from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.models.list import List
from app.models.list_item import ListItem
from app.models.candidate import Candidate
from app.schemas.list import ListCreate, ListUpdate
from app.schemas.list_item import ListItemCreate
from app.repositories.list_repository import ListRepository
from app.repositories.list_item_repository import ListItemRepository
from typing import Optional
from uuid import UUID
import uuid

router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/lists")
async def lists_page(
    request: Request,
    create_success: Optional[str] = None,
    create_error: Optional[str] = None,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Lists index with create form"""
    # Get lists with item counts
    query = (
        select(
            List,
            func.count(ListItem.id).label("item_count")
        )
        .outerjoin(ListItem, List.id == ListItem.list_id)
        .where(List.tenant_id == current_user.tenant_id)
        .group_by(List.id)
        .order_by(List.created_at.desc())
    )
    result = await db.execute(query)
    lists = result.all()
    
    # Convert to list of objects with item_count attribute
    result = []
    for list_obj, item_count in lists:
        list_obj.item_count = item_count
        result.append(list_obj)
    
    return templates.TemplateResponse(
        "lists.html",
        {
            "request": request,
            "current_user": current_user,
            "lists": result,
            "create_success": create_success,
            "create_error": create_error
        }
    )


@router.post("/ui/lists/create")
async def create_list(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Create a new list"""
    # Permission check: admin or consultant can create lists
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "create lists"
    )
    
    try:
        list_create = ListCreate(
            name=name,
            description=description
        )
        
        new_list = List(
            **list_create.dict(),
            tenant_id=str(current_user.tenant_id)
        )
        db.add(new_list)
        await db.commit()
        await db.refresh(new_list)
        
        return RedirectResponse(
            url=f"/ui/lists/{new_list.id}",
            status_code=303
        )
    
    except Exception as e:
        return RedirectResponse(
            url=f"/ui/lists?create_error=Error creating list: {str(e)}",
            status_code=303
        )


@router.get("/ui/lists/{list_id}")
async def list_detail_page(
    request: Request,
    list_id: str,
    add_success: Optional[str] = None,
    add_error: Optional[str] = None,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """List detail with items and add form"""
    try:
        list_uuid = uuid.UUID(list_id)
    except ValueError:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Invalid list ID"},
            status_code=400
        )
    
    # Get list
    result = await db.execute(select(List).where(List.id == list_uuid, List.tenant_id == current_user.tenant_id))
    list_obj = result.scalar_one_or_none()
    
    if not list_obj:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "List not found"},
            status_code=404
        )
    
    # Get list items with candidate details
    items_query = (
        select(ListItem, Candidate)
        .join(
            Candidate,
            and_(
                ListItem.entity_id == Candidate.id,
                ListItem.entity_type == "CANDIDATE"
            )
        )
        .where(
            ListItem.list_id == list_uuid,
            ListItem.tenant_id == current_user.tenant_id
        )
        .order_by(ListItem.created_at.desc())
    )
    result = await db.execute(items_query)
    items_data = result.all()
    
    # Attach candidate to each item for template access
    items = []
    for item, candidate in items_data:
        item.candidate = candidate
        items.append(item)
    
    # Get recent candidates for dropdown
    query = select(Candidate).where(Candidate.tenant_id == current_user.tenant_id).order_by(Candidate.updated_at.desc()).limit(100)
    result = await db.execute(query)
    recent_candidates = result.scalars().all()
    
    return templates.TemplateResponse(
        "list_detail.html",
        {
            "request": request,
            "list": list_obj,
            "items": items,
            "recent_candidates": recent_candidates,
            "add_success": add_success,
            "add_error": add_error
        }
    )


@router.post("/ui/lists/{list_id}/add")
async def add_to_list(
    list_id: str,
    candidate_id: str = Form(...),
    notes: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Add candidate to list"""
    # Permission check: admin or consultant can modify lists
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "modify lists"
    )
    
    try:
        list_uuid = uuid.UUID(list_id)
        candidate_uuid = uuid.UUID(candidate_id)
    except ValueError:
        return RedirectResponse(
            url=f"/ui/lists/{list_id}?add_error=Invalid ID format",
            status_code=303
        )
    
    try:
        # Check if candidate already in list
        result = await db.execute(
            select(ListItem).where(
                ListItem.list_id == list_uuid,
                ListItem.entity_id == candidate_uuid,
                ListItem.entity_type == "CANDIDATE",
                ListItem.tenant_id == current_user.tenant_id
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            return RedirectResponse(
                url=f"/ui/lists/{list_id}?add_error=Candidate already in list",
                status_code=303
            )
        
        # Create list item
        item_create = ListItemCreate(
            list_id=list_uuid,
            entity_type="CANDIDATE",
            entity_id=candidate_uuid
        )
        
        item = ListItem(
            **item_create.dict(),
            tenant_id=str(current_user.tenant_id)
        )
        db.add(item)
        await db.commit()
        
        return RedirectResponse(
            url=f"/ui/lists/{list_id}?add_success=Candidate added to list",
            status_code=303
        )
    
    except Exception as e:
        return RedirectResponse(
            url=f"/ui/lists/{list_id}?add_error=Error adding candidate: {str(e)}",
            status_code=303
        )


@router.get("/ui/lists/{list_id}/edit")
async def list_edit_form(
    request: Request,
    list_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Show list rename form"""
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "edit lists"
    )
    
    # Get list
    result = await db.execute(
        select(List).where(
            List.id == list_id,
            List.tenant_id == current_user.tenant_id
        )
    )
    list_obj = result.scalar_one_or_none()
    
    if not list_obj:
        return RedirectResponse(url="/ui/lists", status_code=303)
    
    return templates.TemplateResponse(
        "list_edit.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "lists",
            "list": list_obj,
        }
    )


@router.post("/ui/lists/{list_id}/edit")
async def list_edit(
    list_id: UUID,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Handle list rename"""
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "edit lists"
    )
    
    # Get list
    result = await db.execute(
        select(List).where(
            List.id == list_id,
            List.tenant_id == current_user.tenant_id
        )
    )
    list_obj = result.scalar_one_or_none()
    
    if not list_obj:
        return RedirectResponse(url="/ui/lists", status_code=303)
    
    try:
        # Update list
        list_update_data = ListUpdate(
            name=name.strip() if name else list_obj.name,
            description=description.strip() if description else None,
        )
        
        list_repo = ListRepository(db)
        await list_repo.update(str(current_user.tenant_id), list_id, list_update_data)
        await db.commit()
        
        return RedirectResponse(
            url=f"/ui/lists/{list_id}?add_success=List+updated+successfully",
            status_code=303
        )
    
    except Exception as e:
        return RedirectResponse(
            url=f"/ui/lists/{list_id}?add_error=Error+updating+list:+{str(e)}",
            status_code=303
        )


@router.post("/ui/lists/items/{item_id}/delete")
async def delete_list_item(
    item_id: UUID,
    list_id: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Remove item from list"""
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "modify lists"
    )
    
    try:
        # Get item
        result = await db.execute(
            select(ListItem).where(
                ListItem.id == item_id,
                ListItem.tenant_id == current_user.tenant_id
            )
        )
        item = result.scalar_one_or_none()
        
        if not item:
            if list_id:
                return RedirectResponse(
                    url=f"/ui/lists/{list_id}?add_error=Item+not+found",
                    status_code=303
                )
            return RedirectResponse(url="/ui/lists", status_code=303)
        
        # Store list_id for redirect
        redirect_list_id = str(item.list_id) if item else list_id
        
        # Delete item
        list_item_repo = ListItemRepository(db)
        await list_item_repo.delete(str(current_user.tenant_id), item_id)
        await db.commit()
        
        if redirect_list_id:
            return RedirectResponse(
                url=f"/ui/lists/{redirect_list_id}?add_success=Item+removed+successfully",
                status_code=303
            )
        return RedirectResponse(url="/ui/lists", status_code=303)
    
    except Exception as e:
        if list_id:
            return RedirectResponse(
                url=f"/ui/lists/{list_id}?add_error=Error+removing+item:+{str(e)}",
                status_code=303
            )
        return RedirectResponse(url="/ui/lists", status_code=303)


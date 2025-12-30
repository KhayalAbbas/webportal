"""
Contacts routes for UI.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.contact import Contact
from app.models.company import Company
from app.repositories.contact_repository import ContactRepository
from app.schemas.contact import ContactCreate, ContactUpdate


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/contacts/new", response_class=HTMLResponse)
async def contact_create_form(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: Optional[str] = None,
):
    """
    Show contact create form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER])
    
    # Get companies for dropdown
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(500)
    )
    companies_result = await session.execute(companies_query)
    companies = companies_result.scalars().all()
    
    # Pre-select company if provided
    preselected_company_id = None
    if company_id:
        try:
            preselected_company_id = UUID(company_id)
        except ValueError:
            pass
    
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "companies",
            "mode": "create",
            "contact": None,
            "companies": companies,
            "preselected_company_id": preselected_company_id,
        }
    )


@router.post("/ui/contacts/new")
async def contact_create(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    role_title: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    bd_status: Optional[str] = Form(None),
    bd_owner: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    work_anniversary_date: Optional[str] = Form(None),
):
    """
    Handle contact create form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER])
    
    try:
        # Parse company_id
        company_uuid = UUID(company_id)
        
        # Create contact
        contact_create_data = ContactCreate(
            tenant_id=str(current_user.tenant_id),
            company_id=company_uuid,
            first_name=first_name.strip() if first_name else "",
            last_name=last_name.strip() if last_name else "",
            email=email.strip() if email else None,
            phone=phone.strip() if phone else None,
            role_title=role_title.strip() if role_title else None,
            notes=notes.strip() if notes else None,
            bd_status=bd_status if bd_status else None,
            bd_owner=bd_owner.strip() if bd_owner else None,
            date_of_birth=date_of_birth if date_of_birth else None,
            work_anniversary_date=work_anniversary_date if work_anniversary_date else None,
        )
        
        contact_repo = ContactRepository(session)
        new_contact = await contact_repo.create(str(current_user.tenant_id), contact_create_data)
        await session.commit()
        
        # Redirect to company detail page with success message
        return RedirectResponse(
            url=f"/ui/companies/{company_uuid}?success_message=Contact+created+successfully",
            status_code=303
        )
        
    except Exception as e:
        # Get companies for dropdown
        companies_query = (
            select(Company)
            .where(Company.tenant_id == current_user.tenant_id)
            .order_by(Company.name)
            .limit(500)
        )
        companies_result = await session.execute(companies_query)
        companies = companies_result.scalars().all()
        
        return templates.TemplateResponse(
            "contact_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "companies",
                "mode": "create",
                "contact": None,
                "companies": companies,
                "error": f"Failed to create contact: {str(e)}",
            },
            status_code=400
        )


@router.get("/ui/contacts/{contact_id}/edit", response_class=HTMLResponse)
async def contact_edit_form(
    request: Request,
    contact_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Show contact edit form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER])
    
    # Get contact
    contact_query = select(Contact).where(
        Contact.tenant_id == current_user.tenant_id,
        Contact.id == contact_id
    )
    contact_result = await session.execute(contact_query)
    contact = contact_result.scalar_one_or_none()
    
    if not contact:
        return RedirectResponse(url="/ui/companies", status_code=303)
    
    # Get companies for dropdown
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(500)
    )
    companies_result = await session.execute(companies_query)
    companies = companies_result.scalars().all()
    
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "companies",
            "mode": "edit",
            "contact": contact,
            "companies": companies,
        }
    )


@router.post("/ui/contacts/{contact_id}/edit")
async def contact_edit(
    request: Request,
    contact_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    role_title: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    bd_status: Optional[str] = Form(None),
    bd_owner: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    work_anniversary_date: Optional[str] = Form(None),
):
    """
    Handle contact edit form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER])
    
    # Get contact
    contact_query = select(Contact).where(
        Contact.tenant_id == current_user.tenant_id,
        Contact.id == contact_id
    )
    contact_result = await session.execute(contact_query)
    contact = contact_result.scalar_one_or_none()
    
    if not contact:
        return RedirectResponse(url="/ui/companies", status_code=303)
    
    try:
        # Parse company_id
        company_uuid = UUID(company_id)
        
        # Update contact
        contact_update_data = ContactUpdate(
            company_id=company_uuid,
            first_name=first_name.strip() if first_name else "",
            last_name=last_name.strip() if last_name else "",
            email=email.strip() if email else None,
            phone=phone.strip() if phone else None,
            role_title=role_title.strip() if role_title else None,
            notes=notes.strip() if notes else None,
            bd_status=bd_status if bd_status else None,
            bd_owner=bd_owner.strip() if bd_owner else None,
            date_of_birth=date_of_birth if date_of_birth else None,
            work_anniversary_date=work_anniversary_date if work_anniversary_date else None,
        )
        
        contact_repo = ContactRepository(session)
        await contact_repo.update(str(current_user.tenant_id), contact_id, contact_update_data)
        await session.commit()
        
        # Redirect to company detail page with success message
        return RedirectResponse(
            url=f"/ui/companies/{company_uuid}?success_message=Contact+updated+successfully",
            status_code=303
        )
        
    except Exception as e:
        # Get companies for dropdown
        companies_query = (
            select(Company)
            .where(Company.tenant_id == current_user.tenant_id)
            .order_by(Company.name)
            .limit(500)
        )
        companies_result = await session.execute(companies_query)
        companies = companies_result.scalars().all()
        
        return templates.TemplateResponse(
            "contact_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "companies",
                "mode": "edit",
                "contact": contact,
                "companies": companies,
                "error": f"Failed to update contact: {str(e)}",
            },
            status_code=400
        )

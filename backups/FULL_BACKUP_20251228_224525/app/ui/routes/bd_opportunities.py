"""
BD Opportunities routes for UI.
"""

from typing import Optional
from uuid import UUID
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.bd_opportunity import BDOpportunity
from app.models.company import Company
from app.models.contact import Contact
from app.repositories.bd_opportunity_repository import BDOpportunityRepository
from app.schemas.bd_opportunity import BDOpportunityCreate, BDOpportunityUpdate


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/bd-opportunities", response_class=HTMLResponse)
async def bd_opportunities_list(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
):
    """
    BD opportunities pipeline view grouped by status.
    """
    
    # Get available companies for filter
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(200)
    )
    companies_result = await session.execute(companies_query)
    available_companies = companies_result.scalars().all()
    
    # Build query with joins
    query = (
        select(BDOpportunity, Company.name.label("company_name"))
        .join(Company, Company.id == BDOpportunity.company_id)
        .where(BDOpportunity.tenant_id == current_user.tenant_id)
    )
    
    # Apply filters
    if company_id:
        try:
            company_uuid = UUID(company_id)
            query = query.where(BDOpportunity.company_id == company_uuid)
        except ValueError:
            pass
    
    if status:
        query = query.where(BDOpportunity.status == status)
    
    if stage:
        query = query.where(BDOpportunity.stage.ilike(f"%{stage}%"))
    
    query = query.order_by(BDOpportunity.updated_at.desc())
    
    result = await session.execute(query)
    rows = result.all()
    
    # Group by status
    grouped = defaultdict(list)
    for row in rows:
        opp = row[0]
        grouped[opp.status or "UNKNOWN"].append({
            "id": opp.id,
            "company_id": opp.company_id,
            "company_name": row.company_name,
            "stage": opp.stage,
            "estimated_value": opp.estimated_value,
            "currency": opp.currency,
            "probability": opp.probability or 0,
            "updated_at": opp.updated_at,
        })
    
    # Convert to list for template
    grouped_opportunities = [
        {"status": status, "opportunities": opps}
        for status, opps in sorted(grouped.items())
    ]
    
    filters = {
        "company_id": company_id,
        "status": status,
        "stage": stage,
    }
    
    return templates.TemplateResponse(
        "bd_opportunities.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "bd",
            "grouped_opportunities": grouped_opportunities,
            "available_companies": available_companies,
            "filters": filters,
        }
    )


@router.get("/ui/bd-opportunities/new", response_class=HTMLResponse)
async def bd_opportunity_create_form(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: Optional[str] = None,
):
    """
    Show BD opportunity create form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.BD_MANAGER, Roles.CONSULTANT])
    
    # Get companies for dropdown
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(500)
    )
    companies_result = await session.execute(companies_query)
    companies = companies_result.scalars().all()
    
    # Get all contacts for dropdown (will be filtered by company in UI)
    contacts_query = (
        select(Contact)
        .where(Contact.tenant_id == current_user.tenant_id)
        .order_by(Contact.first_name, Contact.last_name)
        .limit(500)
    )
    contacts_result = await session.execute(contacts_query)
    contacts = contacts_result.scalars().all()
    
    return templates.TemplateResponse(
        "bd_opportunity_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "bd",
            "mode": "create",
            "bd_opportunity": None,
            "companies": companies,
            "contacts": contacts,
        }
    )


@router.post("/ui/bd-opportunities/new")
async def bd_opportunity_create(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: str = Form(...),
    contact_id: Optional[str] = Form(None),
    status: str = Form("open"),
    stage: Optional[str] = Form(None),
    estimated_value: Optional[str] = Form(None),
    currency: str = Form("USD"),
    probability: Optional[str] = Form(None),
    lost_reason: Optional[str] = Form(None),
    lost_reason_detail: Optional[str] = Form(None),
):
    """
    Handle BD opportunity create form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.BD_MANAGER, Roles.CONSULTANT])
    
    try:
        # Parse UUIDs
        company_uuid = UUID(company_id)
        contact_uuid = UUID(contact_id) if contact_id else None
        
        # Parse numeric values
        estimated_value_float = float(estimated_value) if estimated_value else None
        probability_int = int(probability) if probability else None
        
        # Create BD opportunity
        bd_opportunity_create_data = BDOpportunityCreate(
            tenant_id=str(current_user.tenant_id),
            company_id=company_uuid,
            contact_id=contact_uuid,
            status=status,
            stage=stage if stage else None,
            estimated_value=estimated_value_float,
            currency=currency,
            probability=probability_int,
            lost_reason=lost_reason if lost_reason else None,
            lost_reason_detail=lost_reason_detail.strip() if lost_reason_detail else None,
        )
        
        bd_opp_repo = BDOpportunityRepository(session)
        new_bd_opp = await bd_opp_repo.create(str(current_user.tenant_id), bd_opportunity_create_data)
        await session.commit()
        
        # Redirect to detail page with success message
        return RedirectResponse(
            url=f"/ui/bd-opportunities/{new_bd_opp.id}?success_message=BD+Opportunity+created+successfully",
            status_code=303
        )
        
    except Exception as e:
        # Get companies and contacts for dropdown
        companies_query = (
            select(Company)
            .where(Company.tenant_id == current_user.tenant_id)
            .order_by(Company.name)
            .limit(500)
        )
        companies_result = await session.execute(companies_query)
        companies = companies_result.scalars().all()
        
        contacts_query = (
            select(Contact)
            .where(Contact.tenant_id == current_user.tenant_id)
            .order_by(Contact.first_name, Contact.last_name)
            .limit(500)
        )
        contacts_result = await session.execute(contacts_query)
        contacts = contacts_result.scalars().all()
        
        return templates.TemplateResponse(
            "bd_opportunity_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "bd",
                "mode": "create",
                "bd_opportunity": None,
                "companies": companies,
                "contacts": contacts,
                "error": f"Failed to create BD opportunity: {str(e)}",
            },
            status_code=400
        )


@router.get("/ui/bd-opportunities/{opportunity_id}/edit", response_class=HTMLResponse)
async def bd_opportunity_edit_form(
    request: Request,
    opportunity_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Show BD opportunity edit form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.BD_MANAGER, Roles.CONSULTANT])
    
    # Get BD opportunity
    bd_opp_query = select(BDOpportunity).where(
        BDOpportunity.tenant_id == current_user.tenant_id,
        BDOpportunity.id == opportunity_id
    )
    bd_opp_result = await session.execute(bd_opp_query)
    bd_opp = bd_opp_result.scalar_one_or_none()
    
    if not bd_opp:
        return RedirectResponse(url="/ui/bd-opportunities", status_code=303)
    
    # Get companies for dropdown
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(500)
    )
    companies_result = await session.execute(companies_query)
    companies = companies_result.scalars().all()
    
    # Get all contacts for dropdown
    contacts_query = (
        select(Contact)
        .where(Contact.tenant_id == current_user.tenant_id)
        .order_by(Contact.first_name, Contact.last_name)
        .limit(500)
    )
    contacts_result = await session.execute(contacts_query)
    contacts = contacts_result.scalars().all()
    
    return templates.TemplateResponse(
        "bd_opportunity_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "bd",
            "mode": "edit",
            "bd_opportunity": bd_opp,
            "companies": companies,
            "contacts": contacts,
        }
    )


@router.post("/ui/bd-opportunities/{opportunity_id}/edit")
async def bd_opportunity_edit(
    request: Request,
    opportunity_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    company_id: str = Form(...),
    contact_id: Optional[str] = Form(None),
    status: str = Form("open"),
    stage: Optional[str] = Form(None),
    estimated_value: Optional[str] = Form(None),
    currency: str = Form("USD"),
    probability: Optional[str] = Form(None),
    lost_reason: Optional[str] = Form(None),
    lost_reason_detail: Optional[str] = Form(None),
):
    """
    Handle BD opportunity edit form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.BD_MANAGER, Roles.CONSULTANT])
    
    # Get BD opportunity
    bd_opp_query = select(BDOpportunity).where(
        BDOpportunity.tenant_id == current_user.tenant_id,
        BDOpportunity.id == opportunity_id
    )
    bd_opp_result = await session.execute(bd_opp_query)
    bd_opp = bd_opp_result.scalar_one_or_none()
    
    if not bd_opp:
        return RedirectResponse(url="/ui/bd-opportunities", status_code=303)
    
    try:
        # Parse UUIDs
        company_uuid = UUID(company_id)
        contact_uuid = UUID(contact_id) if contact_id else None
        
        # Parse numeric values
        estimated_value_float = float(estimated_value) if estimated_value else None
        probability_int = int(probability) if probability else None
        
        # Update BD opportunity
        bd_opportunity_update_data = BDOpportunityUpdate(
            company_id=company_uuid,
            contact_id=contact_uuid,
            status=status,
            stage=stage if stage else None,
            estimated_value=estimated_value_float,
            currency=currency,
            probability=probability_int,
            lost_reason=lost_reason if lost_reason else None,
            lost_reason_detail=lost_reason_detail.strip() if lost_reason_detail else None,
        )
        
        bd_opp_repo = BDOpportunityRepository(session)
        await bd_opp_repo.update(str(current_user.tenant_id), opportunity_id, bd_opportunity_update_data)
        await session.commit()
        
        # Redirect to detail page with success message
        return RedirectResponse(
            url=f"/ui/bd-opportunities/{opportunity_id}?success_message=BD+Opportunity+updated+successfully",
            status_code=303
        )
        
    except Exception as e:
        # Get companies and contacts for dropdown
        companies_query = (
            select(Company)
            .where(Company.tenant_id == current_user.tenant_id)
            .order_by(Company.name)
            .limit(500)
        )
        companies_result = await session.execute(companies_query)
        companies = companies_result.scalars().all()
        
        contacts_query = (
            select(Contact)
            .where(Contact.tenant_id == current_user.tenant_id)
            .order_by(Contact.first_name, Contact.last_name)
            .limit(500)
        )
        contacts_result = await session.execute(contacts_query)
        contacts = contacts_result.scalars().all()
        
        return templates.TemplateResponse(
            "bd_opportunity_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "bd",
                "mode": "edit",
                "bd_opportunity": bd_opp,
                "companies": companies,
                "contacts": contacts,
                "error": f"Failed to update BD opportunity: {str(e)}",
            },
            status_code=400
        )


@router.get("/ui/bd-opportunities/{opportunity_id}", response_class=HTMLResponse)
async def bd_opportunity_detail(
    request: Request,
    opportunity_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    success_message: Optional[str] = Query(None),
):
    """
    BD opportunity detail view.
    """
    
    # Get opportunity
    opp_query = select(BDOpportunity).where(
        BDOpportunity.tenant_id == current_user.tenant_id,
        BDOpportunity.id == opportunity_id
    )
    opp_result = await session.execute(opp_query)
    opportunity = opp_result.scalar_one_or_none()
    
    if not opportunity:
        return RedirectResponse(url="/ui/bd-opportunities", status_code=303)
    
    # Get company name
    company_query = select(Company.name).where(Company.id == opportunity.company_id)
    company_result = await session.execute(company_query)
    company_name = company_result.scalar_one_or_none() or "Unknown"
    
    # Get contact name if available
    contact_name = None
    if opportunity.contact_id:
        contact_query = select(Contact).where(Contact.id == opportunity.contact_id)
        contact_result = await session.execute(contact_query)
        contact = contact_result.scalar_one_or_none()
        if contact:
            contact_name = f"{contact.first_name} {contact.last_name}"
    
    return templates.TemplateResponse(
        "bd_opportunity_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "bd",
            "opportunity": opportunity,
            "company_name": company_name,
            "contact_name": contact_name,
            "success_message": success_message,
        }
    )

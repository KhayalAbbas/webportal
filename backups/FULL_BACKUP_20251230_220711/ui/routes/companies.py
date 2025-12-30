"""
Companies routes for UI.
"""

from typing import Optional
from uuid import UUID
from urllib.parse import urlencode
from datetime import date

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.company import Company
from app.models.contact import Contact
from app.models.role import Role
from app.models.bd_opportunity import BDOpportunity
from app.models.candidate_assignment import CandidateAssignment
from app.schemas.company import CompanyCreate, CompanyUpdate
from app.repositories.company_repository import CompanyRepository
from app.services.entity_research_service import EntityResearchService


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/companies", response_class=HTMLResponse)
async def companies_list(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    keyword: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    bd_status: Optional[str] = Query(None),
    is_client: Optional[str] = Query(None),
    is_prospect: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Companies list view with filters.
    """
    
    # Build query
    query = select(Company).where(Company.tenant_id == current_user.tenant_id)
    
    # Apply filters
    if keyword:
        search_filter = or_(
            Company.name.ilike(f"%{keyword}%"),
            Company.website.ilike(f"%{keyword}%"),
            Company.notes.ilike(f"%{keyword}%")
        )
        query = query.where(search_filter)
    
    if country:
        query = query.where(Company.headquarters_location.ilike(f"%{country}%"))
    
    if industry:
        query = query.where(Company.industry.ilike(f"%{industry}%"))
    
    if bd_status:
        query = query.where(Company.bd_status == bd_status)
    
    if is_client == "true":
        query = query.where(Company.is_client == True)
    elif is_client == "false":
        query = query.where(Company.is_client == False)
    
    if is_prospect == "true":
        query = query.where(Company.is_prospect == True)
    elif is_prospect == "false":
        query = query.where(Company.is_prospect == False)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0
    
    # Order and paginate
    query = query.order_by(Company.updated_at.desc()).limit(limit).offset(offset)
    
    result = await session.execute(query)
    companies = result.scalars().all()
    
    # Build filter dict
    filters = {
        "keyword": keyword,
        "country": country,
        "industry": industry,
        "bd_status": bd_status,
        "is_client": is_client,
        "is_prospect": is_prospect,
    }
    
    # Pagination
    current_page = (offset // limit) + 1
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    
    base_params = {k: v for k, v in filters.items() if v is not None}
    base_params["limit"] = limit
    
    prev_params = {**base_params, "offset": max(0, offset - limit)}
    next_params = {**base_params, "offset": offset + limit}
    
    prev_url = urlencode(prev_params)
    next_url = urlencode(next_params)
    
    return templates.TemplateResponse(
        "companies_list.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "companies",
            "companies": companies,
            "filters": filters,
            "total": total,
            "limit": limit,
            "offset": offset,
            "current_page": current_page,
            "total_pages": total_pages,
            "prev_url": prev_url,
            "next_url": next_url,
        }
    )


# CREATE COMPANY ROUTES (must come before /{company_id} routes)

@router.get("/ui/companies/new", response_class=HTMLResponse)
async def new_company_page(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    """Show create company form"""
    # Permission check: admin, consultant, bd_manager
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "create companies"
    )
    
    return templates.TemplateResponse(
        "company_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "company": None,
        }
    )


@router.post("/ui/companies/new")
async def create_company(
    request: Request,
    name: str = Form(...),
    industry: Optional[str] = Form(None),
    headquarters_location: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    bd_status: Optional[str] = Form(None),
    bd_owner: Optional[str] = Form(None),
    bd_last_contacted_at: Optional[str] = Form(None),
    is_client: Optional[str] = Form(None),
    is_prospect: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new company"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "create companies"
    )
    
    try:
        # Parse date if provided
        parsed_bd_date = None
        if bd_last_contacted_at:
            from datetime import datetime
            parsed_bd_date = datetime.fromisoformat(bd_last_contacted_at)
        
        # Create company
        company_data = CompanyCreate(
            tenant_id=str(current_user.tenant_id),
            name=name,
            industry=industry or None,
            headquarters_location=headquarters_location or None,
            website=website or None,
            notes=notes or None,
            bd_status=bd_status or None,
            bd_owner=bd_owner or None,
            bd_last_contacted_at=parsed_bd_date,
            is_client=is_client == "true",
            is_prospect=is_prospect == "true",
        )
        
        repo = CompanyRepository(db)
        company = await repo.create(str(current_user.tenant_id), company_data)
        await db.commit()
        
        # Redirect to company detail with success message
        return RedirectResponse(
            url=f"/ui/companies/{company.id}?msg=Company+created+successfully",
            status_code=303
        )
    
    except Exception as e:
        return templates.TemplateResponse(
            "company_form.html",
            {
                "request": request,
                "current_user": current_user,
                "mode": "create",
                "company": None,
                "error": f"Error creating company: {str(e)}"
            }
        )


# EDIT COMPANY ROUTES (must come before /{company_id} route)

@router.get("/ui/companies/{company_id}/edit", response_class=HTMLResponse)
async def edit_company_page(
    request: Request,
    company_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Show edit company form"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "edit companies"
    )
    
    # Get company
    repo = CompanyRepository(db)
    company = await repo.get_by_id(current_user.tenant_id, company_id)
    
    if not company:
        return RedirectResponse(url="/ui/companies", status_code=303)
    
    return templates.TemplateResponse(
        "company_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "company": company,
        }
    )


@router.post("/ui/companies/{company_id}/edit")
async def update_company(
    request: Request,
    company_id: UUID,
    name: str = Form(...),
    industry: Optional[str] = Form(None),
    headquarters_location: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    bd_status: Optional[str] = Form(None),
    bd_owner: Optional[str] = Form(None),
    bd_last_contacted_at: Optional[str] = Form(None),
    is_client: Optional[str] = Form(None),
    is_prospect: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing company"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "edit companies"
    )
    
    try:
        # Get company
        repo = CompanyRepository(db)
        company = await repo.get_by_id(current_user.tenant_id, company_id)
        
        if not company:
            return RedirectResponse(url="/ui/companies", status_code=303)
        
        # Parse date if provided
        parsed_bd_date = None
        if bd_last_contacted_at:
            from datetime import datetime
            parsed_bd_date = datetime.fromisoformat(bd_last_contacted_at)
        
        # Build update data
        update_data = CompanyUpdate(
            name=name,
            industry=industry or None,
            headquarters_location=headquarters_location or None,
            website=website or None,
            notes=notes or None,
            bd_status=bd_status or None,
            bd_owner=bd_owner or None,
            bd_last_contacted_at=parsed_bd_date,
            is_client=is_client == "true",
            is_prospect=is_prospect == "true",
        )
        
        await repo.update(current_user.tenant_id, company_id, update_data)
        await db.commit()
        
        # Redirect back to detail with success message
        return RedirectResponse(
            url=f"/ui/companies/{company_id}?msg=Company+updated+successfully",
            status_code=303
        )
    
    except Exception as e:
        company = await repo.get_by_id(current_user.tenant_id, company_id)
        return templates.TemplateResponse(
            "company_form.html",
            {
                "request": request,
                "current_user": current_user,
                "mode": "edit",
                "company": company,
                "error": f"Error updating company: {str(e)}"
            }
        )


# COMPANY DETAIL ROUTE (must come after /new and /{id}/edit routes)

@router.get("/ui/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(
    request: Request,
    company_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Company detail view with contacts, roles, BD opportunities, and research.
    """
    
    # Get company
    company_query = select(Company).where(
        Company.tenant_id == current_user.tenant_id,
        Company.id == company_id
    )
    company_result = await session.execute(company_query)
    company = company_result.scalar_one_or_none()
    
    if not company:
        return RedirectResponse(url="/ui/companies", status_code=303)
    
    # Get contacts
    contacts_query = (
        select(Contact)
        .where(
            Contact.tenant_id == current_user.tenant_id,
            Contact.company_id == company_id
        )
        .order_by(Contact.last_name)
    )
    contacts_result = await session.execute(contacts_query)
    contacts = contacts_result.scalars().all()
    
    # Get roles with candidate counts
    roles_query = (
        select(
            Role,
            func.count(CandidateAssignment.id).label("candidate_count")
        )
        .outerjoin(
            CandidateAssignment,
            and_(
                CandidateAssignment.role_id == Role.id,
                CandidateAssignment.tenant_id == current_user.tenant_id
            )
        )
        .where(
            Role.tenant_id == current_user.tenant_id,
            Role.company_id == company_id
        )
        .group_by(Role.id)
        .order_by(Role.updated_at.desc())
    )
    roles_result = await session.execute(roles_query)
    roles_rows = roles_result.all()
    
    roles = []
    for row in roles_rows:
        role = row[0]
        roles.append({
            "id": role.id,
            "title": role.title,
            "status": role.status,
            "location": role.location,
            "candidate_count": row.candidate_count,
            "updated_at": role.updated_at,
        })
    
    # Get BD opportunities
    bd_query = (
        select(BDOpportunity)
        .where(
            BDOpportunity.tenant_id == current_user.tenant_id,
            BDOpportunity.company_id == company_id
        )
        .order_by(BDOpportunity.updated_at.desc())
    )
    bd_result = await session.execute(bd_query)
    bd_opportunities = bd_result.scalars().all()
    
    # Get research data
    research_service = EntityResearchService(session)
    research = await research_service.get_entity_research(
        tenant_id=current_user.tenant_id,
        entity_type="COMPANY",
        entity_id=company_id
    )
    
    # Check for success message
    msg = request.query_params.get("msg", "")
    
    return templates.TemplateResponse(
        "company_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "companies",
            "company": company,
            "contacts": contacts,
            "roles": roles,
            "bd_opportunities": bd_opportunities,
            "research": research,
            "success_message": msg,
        }
    )

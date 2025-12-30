"""
Roles routes for UI.
"""

from typing import Optional
from uuid import UUID
from urllib.parse import urlencode
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.role import Role
from app.models.company import Company
from app.models.candidate import Candidate
from app.models.candidate_assignment import CandidateAssignment
from app.models.pipeline_stage import PipelineStage
from app.repositories.candidate_assignment_repository import CandidateAssignmentRepository
from app.repositories.role_repository import RoleRepository
from app.schemas.role import RoleCreate, RoleUpdate


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/roles", response_class=HTMLResponse)
async def roles_list(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    keyword: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Roles list view with filters.
    """
    
    # Get available companies for filter dropdown
    companies_query = (
        select(Company)
        .where(Company.tenant_id == current_user.tenant_id)
        .order_by(Company.name)
        .limit(200)
    )
    companies_result = await session.execute(companies_query)
    available_companies = companies_result.scalars().all()
    
    # Build roles query with filters
    query = (
        select(
            Role,
            Company.name.label("company_name"),
            func.count(CandidateAssignment.id).label("candidate_count")
        )
        .join(Company, Company.id == Role.company_id)
        .outerjoin(
            CandidateAssignment,
            and_(
                CandidateAssignment.role_id == Role.id,
                CandidateAssignment.tenant_id == current_user.tenant_id
            )
        )
        .where(Role.tenant_id == current_user.tenant_id)
        .group_by(Role.id, Company.name)
    )
    
    # Apply filters
    if keyword:
        search_filter = or_(
            Role.title.ilike(f"%{keyword}%"),
            Role.location.ilike(f"%{keyword}%"),
            Role.description.ilike(f"%{keyword}%")
        )
        query = query.where(search_filter)
    
    if company_id:
        try:
            company_uuid = UUID(company_id)
            query = query.where(Role.company_id == company_uuid)
        except ValueError:
            pass
    
    if status:
        query = query.where(Role.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0
    
    # Order and paginate
    query = query.order_by(Role.updated_at.desc()).limit(limit).offset(offset)
    
    result = await session.execute(query)
    rows = result.all()
    
    roles = []
    for row in rows:
        role = row[0]
        roles.append({
            "id": role.id,
            "title": role.title,
            "company_id": role.company_id,
            "company_name": row.company_name,
            "location": role.location,
            "status": role.status,
            "candidate_count": row.candidate_count,
            "updated_at": role.updated_at,
        })
    
    # Build filter dict
    filters = {
        "keyword": keyword,
        "company_id": company_id,
        "status": status,
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
        "roles_list.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "roles",
            "roles": roles,
            "filters": filters,
            "available_companies": available_companies,
            "total": total,
            "limit": limit,
            "offset": offset,
            "current_page": current_page,
            "total_pages": total_pages,
            "prev_url": prev_url,
            "next_url": next_url,
        }
    )


@router.get("/ui/roles/new", response_class=HTMLResponse)
async def role_create_form(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Show role create form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
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
        "role_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "roles",
            "mode": "create",
            "role": None,
            "companies": companies,
        }
    )


@router.post("/ui/roles/new")
async def role_create(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    title: str = Form(...),
    company_id: str = Form(...),
    function: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    status: str = Form("OPEN"),
    seniority_level: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
):
    """
    Handle role create form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    try:
        # Parse company_id
        company_uuid = UUID(company_id)
        
        # Create role
        role_create_data = RoleCreate(
            tenant_id=str(current_user.tenant_id),
            title=title.strip() if title else "",
            company_id=company_uuid,
            function=function.strip() if function else None,
            location=location.strip() if location else None,
            status=status,
            seniority_level=seniority_level.strip() if seniority_level else None,
            description=description.strip() if description else None,
        )
        
        role_repo = RoleRepository(session)
        new_role = await role_repo.create(str(current_user.tenant_id), role_create_data)
        await session.commit()
        
        # Redirect to detail page with success message
        return RedirectResponse(
            url=f"/ui/roles/{new_role.id}?success_message=Role+created+successfully",
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
            "role_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "roles",
                "mode": "create",
                "role": None,
                "companies": companies,
                "error": f"Failed to create role: {str(e)}",
            },
            status_code=400
        )


@router.get("/ui/roles/{role_id}/edit", response_class=HTMLResponse)
async def role_edit_form(
    request: Request,
    role_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Show role edit form.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    # Get role
    role_query = select(Role).where(
        Role.tenant_id == current_user.tenant_id,
        Role.id == role_id
    )
    role_result = await session.execute(role_query)
    role = role_result.scalar_one_or_none()
    
    if not role:
        return RedirectResponse(url="/ui/roles", status_code=303)
    
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
        "role_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "roles",
            "mode": "edit",
            "role": role,
            "companies": companies,
        }
    )


@router.post("/ui/roles/{role_id}/edit")
async def role_edit(
    request: Request,
    role_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    title: str = Form(...),
    company_id: str = Form(...),
    function: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    status: str = Form("OPEN"),
    seniority_level: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
):
    """
    Handle role edit form submission.
    """
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT])
    
    # Get role
    role_query = select(Role).where(
        Role.tenant_id == current_user.tenant_id,
        Role.id == role_id
    )
    role_result = await session.execute(role_query)
    role = role_result.scalar_one_or_none()
    
    if not role:
        return RedirectResponse(url="/ui/roles", status_code=303)
    
    try:
        # Parse company_id
        company_uuid = UUID(company_id)
        
        # Update role
        role_update_data = RoleUpdate(
            title=title.strip() if title else "",
            company_id=company_uuid,
            function=function.strip() if function else None,
            location=location.strip() if location else None,
            status=status,
            seniority_level=seniority_level.strip() if seniority_level else None,
            description=description.strip() if description else None,
        )
        
        role_repo = RoleRepository(session)
        await role_repo.update(str(current_user.tenant_id), role_id, role_update_data)
        await session.commit()
        
        # Redirect to detail page with success message
        return RedirectResponse(
            url=f"/ui/roles/{role_id}?success_message=Role+updated+successfully",
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
            "role_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "roles",
                "mode": "edit",
                "role": role,
                "companies": companies,
                "error": f"Failed to update role: {str(e)}",
            },
            status_code=400
        )


@router.get("/ui/roles/{role_id}", response_class=HTMLResponse)
async def role_detail(
    request: Request,
    role_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    add_success: Optional[str] = Query(None),
    add_error: Optional[str] = Query(None),
    success_message: Optional[str] = Query(None),
):
    """
    Role detail view with pipeline and add candidate form.
    """
    
    # Get role
    role_query = select(Role).where(
        Role.tenant_id == current_user.tenant_id,
        Role.id == role_id
    )
    role_result = await session.execute(role_query)
    role = role_result.scalar_one_or_none()
    
    if not role:
        return RedirectResponse(url="/ui/roles", status_code=303)
    
    # Get company name
    company_query = select(Company.name).where(Company.id == role.company_id)
    company_result = await session.execute(company_query)
    company_name = company_result.scalar_one_or_none() or "Unknown"
    
    # Get candidate pipeline
    pipeline_query = (
        select(
            CandidateAssignment,
            Candidate.first_name,
            Candidate.last_name,
            Candidate.current_title,
            Candidate.current_company,
            PipelineStage.name.label("stage_name")
        )
        .join(Candidate, Candidate.id == CandidateAssignment.candidate_id)
        .outerjoin(PipelineStage, PipelineStage.id == CandidateAssignment.current_stage_id)
        .where(
            CandidateAssignment.tenant_id == current_user.tenant_id,
            CandidateAssignment.role_id == role_id
        )
        .order_by(CandidateAssignment.updated_at.desc())
    )
    
    pipeline_result = await session.execute(pipeline_query)
    pipeline_rows = pipeline_result.all()
    
    pipeline = []
    for row in pipeline_rows:
        assignment = row[0]
        pipeline.append({
            "candidate_id": assignment.candidate_id,
            "candidate_name": f"{row.first_name} {row.last_name}",
            "current_title": row.current_title,
            "current_company": row.current_company,
            "status": assignment.status,
            "is_hot": assignment.is_hot,
            "stage_name": row.stage_name,
            "date_entered": assignment.date_entered,
            "updated_at": assignment.updated_at,
        })
    
    # Get recent candidates for dropdown (last 100)
    recent_candidates_query = (
        select(Candidate)
        .where(Candidate.tenant_id == current_user.tenant_id)
        .order_by(Candidate.updated_at.desc())
        .limit(100)
    )
    recent_candidates_result = await session.execute(recent_candidates_query)
    recent_candidates = recent_candidates_result.scalars().all()
    
    return templates.TemplateResponse(
        "role_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "roles",
            "role": role,
            "company_name": company_name,
            "pipeline": pipeline,
            "recent_candidates": recent_candidates,
            "add_success": add_success,
            "add_error": add_error,
            "success_message": success_message,
        }
    )


@router.post("/ui/roles/{role_id}/add-candidate")
async def add_candidate_to_role(
    role_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    candidate_id: UUID = Form(...),
    status: str = Form(...),
    is_hot: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
):
    """
    Add a candidate to a role (create CandidateAssignment).
    """
    # Permission check: admin or consultant can assign candidates
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "assign candidates to roles"
    )
    
    # Check if assignment already exists
    existing_query = select(CandidateAssignment).where(
        CandidateAssignment.tenant_id == current_user.tenant_id,
        CandidateAssignment.role_id == role_id,
        CandidateAssignment.candidate_id == candidate_id
    )
    existing_result = await session.execute(existing_query)
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        return RedirectResponse(
            url=f"/ui/roles/{role_id}?add_error=Candidate+already+assigned+to+this+role",
            status_code=303
        )
    
    # Create assignment
    assignment_repo = CandidateAssignmentRepository(session)
    
    from app.schemas.candidate_assignment import CandidateAssignmentCreate
    assignment_data = CandidateAssignmentCreate(
        candidate_id=candidate_id,
        role_id=role_id,
        status=status,
        is_hot=bool(is_hot),
        source=source,
        date_entered=datetime.utcnow(),
    )
    
    await assignment_repo.create(current_user.tenant_id, assignment_data)
    await session.commit()
    
    return RedirectResponse(
        url=f"/ui/roles/{role_id}?add_success=Candidate+added+successfully",
        status_code=303
    )

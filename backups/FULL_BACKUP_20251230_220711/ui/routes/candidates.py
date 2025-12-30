"""
Candidates routes for UI.
"""

from typing import Optional
from uuid import UUID
from urllib.parse import urlencode
from datetime import date

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.services.search_service import SearchService
from app.services.entity_research_service import EntityResearchService
from app.repositories.candidate_repository import CandidateRepository
from app.schemas.candidate import CandidateCreate, CandidateUpdate
from app.models.role import Role
from app.models.company import Company
from app.models.candidate_assignment import CandidateAssignment
from app.models.pipeline_stage import PipelineStage


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/candidates", response_class=HTMLResponse)
async def candidates_list(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None),
    home_country: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    current_title: Optional[str] = Query(None),
    current_company: Optional[str] = Query(None),
    languages: Optional[str] = Query(None),
    promotability_min: Optional[int] = Query(None),
    promotability_max: Optional[int] = Query(None),
    assignment_role_id: Optional[str] = Query(None),
    assignment_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Candidate list view with filters.
    
    List-first approach showing all candidates by default.
    """
    
    # Get available roles for filter dropdown
    roles_query = (
        select(Role, Company.name.label("company_name"))
        .join(Company, Company.id == Role.company_id)
        .where(Role.tenant_id == current_user.tenant_id)
        .order_by(Role.updated_at.desc())
        .limit(100)
    )
    roles_result = await session.execute(roles_query)
    roles_rows = roles_result.all()
    
    available_roles = []
    for row in roles_rows:
        role = row[0]
        available_roles.append({
            "id": role.id,
            "title": role.title,
            "company_name": row.company_name,
        })
    
    # Parse assignment_role_id if provided
    assignment_role_uuid = None
    if assignment_role_id:
        try:
            assignment_role_uuid = UUID(assignment_role_id)
        except ValueError:
            pass
    
    # Execute search
    search_service = SearchService(session)
    results = await search_service.search_candidates(
        tenant_id=current_user.tenant_id,
        q=q,
        home_country=home_country,
        location=location,
        current_title=current_title,
        current_company=current_company,
        languages=languages,
        promotability_min=promotability_min,
        promotability_max=promotability_max,
        assignment_role_id=assignment_role_uuid,
        assignment_status=assignment_status,
        limit=limit,
        offset=offset,
    )
    
    # Build filter dict for template
    filters = {
        "q": q,
        "home_country": home_country,
        "location": location,
        "current_title": current_title,
        "current_company": current_company,
        "languages": languages,
        "promotability_min": promotability_min,
        "promotability_max": promotability_max,
        "assignment_role_id": assignment_role_id,
        "assignment_status": assignment_status,
    }
    
    # Build pagination URLs
    current_page = (offset // limit) + 1
    total_pages = (results.total + limit - 1) // limit if results.total > 0 else 1
    
    # Build query params for prev/next
    base_params = {k: v for k, v in filters.items() if v is not None}
    base_params["limit"] = limit
    
    prev_params = {**base_params, "offset": max(0, offset - limit)}
    next_params = {**base_params, "offset": offset + limit}
    
    prev_url = urlencode(prev_params)
    next_url = urlencode(next_params)
    
    return templates.TemplateResponse(
        "candidates_list.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "candidates",
            "results": results,
            "filters": filters,
            "available_roles": available_roles,
            "limit": limit,
            "offset": offset,
            "current_page": current_page,
            "total_pages": total_pages,
            "prev_url": prev_url,
            "next_url": next_url,
        }
    )


# CREATE CANDIDATE ROUTES (must come before /{candidate_id} routes)

@router.get("/ui/candidates/new", response_class=HTMLResponse)
async def new_candidate_page(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    """Show create candidate form"""
    # Permission check: only admin and consultant
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "create candidates"
    )
    
    return templates.TemplateResponse(
        "candidate_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "candidate": None,
        }
    )


@router.post("/ui/candidates/new")
async def create_candidate(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email_1: Optional[str] = Form(None),
    email_2: Optional[str] = Form(None),
    mobile_1: Optional[str] = Form(None),
    mobile_2: Optional[str] = Form(None),
    home_country: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    marital_status: Optional[str] = Form(None),
    children_count: Optional[int] = Form(None),
    current_title: Optional[str] = Form(None),
    current_company: Optional[str] = Form(None),
    salary_details: Optional[str] = Form(None),
    languages: Optional[str] = Form(None),
    qualifications: Optional[str] = Form(None),
    certifications: Optional[str] = Form(None),
    education_summary: Optional[str] = Form(None),
    promotability_score: Optional[int] = Form(None),
    technical_score: Optional[int] = Form(None),
    gamification_score: Optional[int] = Form(None),
    bio: Optional[str] = Form(None),
    cv_text: Optional[str] = Form(None),
    social_links: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new candidate"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "create candidates"
    )
    
    try:
        # Parse date if provided
        parsed_dob = None
        if date_of_birth:
            from datetime import datetime
            parsed_dob = datetime.fromisoformat(date_of_birth)
        
        # Create candidate
        candidate_data = CandidateCreate(
            tenant_id=str(current_user.tenant_id),
            first_name=first_name,
            last_name=last_name,
            email_1=email_1 or None,
            email_2=email_2 or None,
            mobile_1=mobile_1 or None,
            mobile_2=mobile_2 or None,
            home_country=home_country or None,
            location=location or None,
            date_of_birth=parsed_dob,
            marital_status=marital_status or None,
            children_count=children_count,
            current_title=current_title or None,
            current_company=current_company or None,
            salary_details=salary_details or None,
            languages=languages or None,
            qualifications=qualifications or None,
            certifications=certifications or None,
            education_summary=education_summary or None,
            promotability_score=promotability_score,
            technical_score=technical_score,
            gamification_score=gamification_score,
            bio=bio or None,
            cv_text=cv_text or None,
            social_links=social_links or None,
        )
        
        repo = CandidateRepository(db)
        candidate = await repo.create(str(current_user.tenant_id), candidate_data)
        await db.commit()
        
        # Redirect to candidate detail with success message
        return RedirectResponse(
            url=f"/ui/candidates/{candidate.id}?msg=Candidate+created+successfully",
            status_code=303
        )
    
    except Exception as e:
        return templates.TemplateResponse(
            "candidate_form.html",
            {
                "request": request,
                "current_user": current_user,
                "mode": "create",
                "candidate": None,
                "error": f"Error creating candidate: {str(e)}"
            }
        )


# EDIT CANDIDATE ROUTES (must come before /{candidate_id} route)

@router.get("/ui/candidates/{candidate_id}/edit", response_class=HTMLResponse)
async def edit_candidate_page(
    request: Request,
    candidate_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Show edit candidate form"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "edit candidates"
    )
    
    # Get candidate
    repo = CandidateRepository(db)
    candidate = await repo.get_by_id(current_user.tenant_id, candidate_id)
    
    if not candidate:
        return RedirectResponse(url="/ui/candidates", status_code=303)
    
    return templates.TemplateResponse(
        "candidate_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "candidate": candidate,
        }
    )


@router.post("/ui/candidates/{candidate_id}/edit")
async def update_candidate(
    request: Request,
    candidate_id: UUID,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email_1: Optional[str] = Form(None),
    email_2: Optional[str] = Form(None),
    mobile_1: Optional[str] = Form(None),
    mobile_2: Optional[str] = Form(None),
    home_country: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    marital_status: Optional[str] = Form(None),
    children_count: Optional[int] = Form(None),
    current_title: Optional[str] = Form(None),
    current_company: Optional[str] = Form(None),
    salary_details: Optional[str] = Form(None),
    languages: Optional[str] = Form(None),
    qualifications: Optional[str] = Form(None),
    certifications: Optional[str] = Form(None),
    education_summary: Optional[str] = Form(None),
    promotability_score: Optional[int] = Form(None),
    technical_score: Optional[int] = Form(None),
    gamification_score: Optional[int] = Form(None),
    bio: Optional[str] = Form(None),
    cv_text: Optional[str] = Form(None),
    social_links: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing candidate"""
    # Permission check
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT],
        "edit candidates"
    )
    
    try:
        # Get candidate
        repo = CandidateRepository(db)
        candidate = await repo.get_by_id(current_user.tenant_id, candidate_id)
        
        if not candidate:
            return RedirectResponse(url="/ui/candidates", status_code=303)
        
        # Parse date if provided
        parsed_dob = None
        if date_of_birth:
            from datetime import datetime
            parsed_dob = datetime.fromisoformat(date_of_birth)
        
        # Update candidate
        update_data = CandidateUpdate(
            first_name=first_name,
            last_name=last_name,
            email_1=email_1 or None,
            email_2=email_2 or None,
            mobile_1=mobile_1 or None,
            mobile_2=mobile_2 or None,
            home_country=home_country or None,
            location=location or None,
            date_of_birth=parsed_dob,
            marital_status=marital_status or None,
            children_count=children_count,
            current_title=current_title or None,
            current_company=current_company or None,
            salary_details=salary_details or None,
            languages=languages or None,
            qualifications=qualifications or None,
            certifications=certifications or None,
            education_summary=education_summary or None,
            promotability_score=promotability_score,
            technical_score=technical_score,
            gamification_score=gamification_score,
            bio=bio or None,
            cv_text=cv_text or None,
            social_links=social_links or None,
        )
        
        await repo.update(current_user.tenant_id, candidate_id, update_data)
        await db.commit()
        
        # Redirect back to detail with success message
        return RedirectResponse(
            url=f"/ui/candidates/{candidate_id}?msg=Candidate+updated+successfully",
            status_code=303
        )
    
    except Exception as e:
        candidate = await repo.get_by_id(current_user.tenant_id, candidate_id)
        return templates.TemplateResponse(
            "candidate_form.html",
            {
                "request": request,
                "current_user": current_user,
                "mode": "edit",
                "candidate": candidate,
                "error": f"Error updating candidate: {str(e)}"
            }
        )


# CANDIDATE DETAIL ROUTE (must come after /new and /{id}/edit routes)


@router.get("/ui/candidates/{candidate_id}", response_class=HTMLResponse)
async def candidate_detail(
    request: Request,
    candidate_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Candidate detail view with profile, assignments, and research.
    """
    
    # Get candidate
    candidate_repo = CandidateRepository(session)
    candidate = await candidate_repo.get_by_id(current_user.tenant_id, candidate_id)
    
    if not candidate:
        # Could return 404 page, but for now just redirect
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/ui/candidates", status_code=303)
    
    # Get assignments with role and company info
    assignments_query = (
        select(
            CandidateAssignment,
            Role.title.label("role_title"),
            Company.name.label("company_name"),
            PipelineStage.name.label("stage_name")
        )
        .join(Role, Role.id == CandidateAssignment.role_id)
        .join(Company, Company.id == Role.company_id)
        .outerjoin(PipelineStage, PipelineStage.id == CandidateAssignment.current_stage_id)
        .where(
            CandidateAssignment.tenant_id == current_user.tenant_id,
            CandidateAssignment.candidate_id == candidate_id
        )
        .order_by(CandidateAssignment.updated_at.desc())
    )
    
    assignments_result = await session.execute(assignments_query)
    assignments_rows = assignments_result.all()
    
    assignments = []
    for row in assignments_rows:
        assignment = row[0]
        assignments.append({
            "role_id": assignment.role_id,
            "role_title": row.role_title,
            "company_name": row.company_name,
            "status": assignment.status,
            "is_hot": assignment.is_hot,
            "date_entered": assignment.date_entered,
            "start_date": assignment.start_date,
            "stage_name": row.stage_name,
        })
    
    # Get research data
    research_service = EntityResearchService(session)
    research = await research_service.get_entity_research(
        tenant_id=current_user.tenant_id,
        entity_type="CANDIDATE",
        entity_id=candidate_id
    )
    
    # Check for success message
    msg = request.query_params.get("msg", "")
    
    return templates.TemplateResponse(
        "candidate_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "candidates",
            "candidate": candidate,
            "assignments": assignments,
            "research": research,
            "success_message": msg,
        }
    )

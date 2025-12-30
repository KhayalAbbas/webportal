"""
Dashboard route for UI.
"""

from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.role import Role
from app.models.company import Company
from app.models.candidate import Candidate
from app.models.candidate_assignment import CandidateAssignment
from app.models.task import Task
from app.models.bd_opportunity import BDOpportunity


router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Dashboard home screen with tables showing active work.
    """
    
    # A. My Active Roles
    # Get roles with candidate counts
    roles_query = (
        select(
            Role,
            Company.name.label("company_name"),
            func.count(CandidateAssignment.id).label("candidate_count")
        )
        .join(Company, and_(Company.id == Role.company_id, Company.tenant_id == current_user.tenant_id))
        .outerjoin(
            CandidateAssignment,
            and_(
                CandidateAssignment.role_id == Role.id,
                CandidateAssignment.tenant_id == current_user.tenant_id
            )
        )
        .where(Role.tenant_id == current_user.tenant_id)
        .group_by(Role.id, Company.name)
        .order_by(Role.updated_at.desc())
        .limit(10)
    )
    
    roles_result = await session.execute(roles_query)
    roles_rows = roles_result.all()
    
    active_roles = []
    for row in roles_rows:
        role = row[0]
        active_roles.append({
            "id": role.id,
            "title": role.title,
            "company_name": row.company_name,
            "status": role.status,
            "candidate_count": row.candidate_count,
            "updated_at": role.updated_at,
        })
    
    # B. Candidates Requiring Action
    # Get candidate assignments that are in process (not PLACED or REJECTED)
    action_query = (
        select(
            CandidateAssignment,
            Candidate.first_name,
            Candidate.last_name,
            Role.title.label("role_title"),
        )
        .join(Candidate, and_(Candidate.id == CandidateAssignment.candidate_id, Candidate.tenant_id == current_user.tenant_id))
        .join(Role, and_(Role.id == CandidateAssignment.role_id, Role.tenant_id == current_user.tenant_id))
        .where(
            CandidateAssignment.tenant_id == current_user.tenant_id,
            CandidateAssignment.status.not_in(["PLACED", "REJECTED"])
        )
        .order_by(CandidateAssignment.updated_at.desc())
        .limit(20)
    )
    
    action_result = await session.execute(action_query)
    action_rows = action_result.all()
    
    action_candidates = []
    for row in action_rows:
        assignment = row[0]
        action_candidates.append({
            "candidate_id": assignment.candidate_id,
            "candidate_name": f"{row.first_name} {row.last_name}",
            "role_id": assignment.role_id,
            "role_title": row.role_title,
            "status": assignment.status,
            "is_hot": assignment.is_hot,
            "last_interaction": assignment.updated_at,
        })
    
    # C. My Tasks
    # Get tasks assigned to current user
    tasks_query = (
        select(Task)
        .where(
            Task.tenant_id == current_user.tenant_id,
            # For now, show all tasks; later can filter by assigned_to_user
        )
        .order_by(Task.due_date.asc().nulls_last())
        .limit(15)
    )
    
    tasks_result = await session.execute(tasks_query)
    tasks = tasks_result.scalars().all()
    
    my_tasks = []
    for task in tasks:
        # Try to resolve related entity name (simplified)
        related_entity_name = None
        if task.related_entity_type and task.related_entity_id:
            # Could query for name, but keep it simple for now
            related_entity_name = str(task.related_entity_id)[:8]
        
        my_tasks.append({
            "title": task.title,
            "related_entity_type": task.related_entity_type,
            "related_entity_name": related_entity_name,
            "due_date": task.due_date,
            "status": task.status,
        })
    
    # D. BD Snapshot
    # Get active BD opportunities
    bd_query = (
        select(BDOpportunity, Company.name.label("company_name"))
        .join(Company, and_(Company.id == BDOpportunity.company_id, Company.tenant_id == current_user.tenant_id))
        .where(BDOpportunity.tenant_id == current_user.tenant_id)
        .order_by(BDOpportunity.updated_at.desc())
        .limit(10)
    )
    
    bd_result = await session.execute(bd_query)
    bd_rows = bd_result.all()
    
    bd_opportunities = []
    for row in bd_rows:
        opp = row[0]
        bd_opportunities.append({
            "company_name": row.company_name,
            "status": opp.status,
            "stage": opp.stage,
            "estimated_value": opp.estimated_value,
            "probability": opp.probability or 0,
            "updated_at": opp.updated_at,
        })
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "dashboard",
            "active_roles": active_roles,
            "action_candidates": action_candidates,
            "my_tasks": my_tasks,
            "bd_opportunities": bd_opportunities,
        }
    )

from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.core.dependencies import get_db
from app.core.permissions import raise_if_not_roles, Roles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.task import Task
from app.models.candidate import Candidate
from app.models.role import Role
from app.models.company import Company
from app.models.contact import Contact
from app.schemas.task import TaskCreate, TaskUpdate
from app.repositories.task_repository import TaskRepository
from datetime import datetime
from typing import Optional
from uuid import UUID
import uuid

router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/ui/tasks")
async def tasks_page(
    request: Request,
    status_filter: Optional[str] = None,
    due_before: Optional[str] = None,
    create_success: Optional[str] = None,
    create_error: Optional[str] = None,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Tasks list with filters and create form"""
    query = select(Task).where(Task.tenant_id == current_user.tenant_id)
    
    # Apply filters
    if status_filter:
        query = query.where(Task.status == status_filter)
    
    if due_before:
        try:
            due_before_date = datetime.strptime(due_before, "%Y-%m-%d").date()
            query = query.where(Task.due_date <= due_before_date)
        except ValueError:
            pass
    
    # Get tasks
    query = query.order_by(Task.due_date.asc().nullsfirst(), Task.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    # Resolve related entity names
    for task in tasks:
        task.related_entity_name = None
        if task.related_entity_id and task.related_entity_type:
            if task.related_entity_type == "CANDIDATE":
                result = await db.execute(select(Candidate).where(Candidate.id == task.related_entity_id, Candidate.tenant_id == current_user.tenant_id))
                candidate = result.scalar_one_or_none()
                if candidate:
                    task.related_entity_name = f"{candidate.first_name} {candidate.last_name}"
            elif task.related_entity_type == "ROLE":
                result = await db.execute(select(Role).where(Role.id == task.related_entity_id, Role.tenant_id == current_user.tenant_id))
                role = result.scalar_one_or_none()
                if role:
                    task.related_entity_name = role.title
            elif task.related_entity_type == "COMPANY":
                result = await db.execute(select(Company).where(Company.id == task.related_entity_id, Company.tenant_id == current_user.tenant_id))
                company = result.scalar_one_or_none()
                if company:
                    task.related_entity_name = company.name
            elif task.related_entity_type == "CONTACT":
                result = await db.execute(select(Contact).where(Contact.id == task.related_entity_id, Contact.tenant_id == current_user.tenant_id))
                contact = result.scalar_one_or_none()
                if contact:
                    task.related_entity_name = f"{contact.first_name} {contact.last_name}"
    
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "current_user": current_user,
            "tasks": tasks,
            "filters": {
                "status_filter": status_filter,
                "due_before": due_before
            },
            "create_success": create_success,
            "create_error": create_error
        }
    )


@router.post("/ui/tasks/create")
async def create_task(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    related_entity_type: Optional[str] = Form(None),
    related_entity_id: Optional[str] = Form(None),
    due_date: Optional[str] = Form(None),
    status: str = Form("OPEN"),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Create a new task"""
    # Permission check: admin, consultant, or bd_manager can create tasks
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "create tasks"
    )
    
    try:
        # Parse related_entity_id as UUID if provided
        entity_id = None
        if related_entity_id and related_entity_id.strip():
            try:
                entity_id = uuid.UUID(related_entity_id)
            except ValueError:
                return RedirectResponse(
                    url=f"/ui/tasks?create_error=Invalid entity ID format",
                    status_code=303
                )
        
        # Parse date if provided
        parsed_due_date = None
        if due_date:
            from datetime import datetime
            parsed_due_date = datetime.fromisoformat(due_date)
        
        # Create task
        task_create = TaskCreate(
            title=title,
            description=description,
            related_entity_type=related_entity_type if related_entity_type else None,
            related_entity_id=entity_id,
            due_date=parsed_due_date,
            status=status,
            assigned_to_user=current_user.user_id
        )
        
        task = Task(
            **task_create.dict(),
            tenant_id=str(current_user.tenant_id)
        )
        db.add(task)
        await db.commit()
        
        return RedirectResponse(
            url=f"/ui/tasks?create_success=Task created successfully",
            status_code=303
        )
    
    except Exception as e:
        return RedirectResponse(
            url=f"/ui/tasks?create_error=Error creating task: {str(e)}",
            status_code=303
        )


@router.get("/ui/tasks/{task_id}/edit")
async def task_edit_form(
    request: Request,
    task_id: UUID,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Show task edit form"""
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "edit tasks"
    )
    
    # Get task
    task_query = select(Task).where(
        Task.tenant_id == current_user.tenant_id,
        Task.id == task_id
    )
    result = await db.execute(task_query)
    task = result.scalar_one_or_none()
    
    if not task:
        return RedirectResponse(url="/ui/tasks", status_code=303)
    
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "tasks",
            "mode": "edit",
            "task": task,
        }
    )


@router.post("/ui/tasks/{task_id}/edit")
async def task_edit(
    request: Request,
    task_id: UUID,
    title: str = Form(...),
    description: Optional[str] = Form(None),
    related_entity_type: Optional[str] = Form(None),
    related_entity_id: Optional[str] = Form(None),
    due_date: Optional[str] = Form(None),
    status: str = Form("pending"),
    assigned_to_user: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Handle task edit form submission"""
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN, Roles.CONSULTANT, Roles.BD_MANAGER],
        "edit tasks"
    )
    
    # Get task
    task_query = select(Task).where(
        Task.tenant_id == current_user.tenant_id,
        Task.id == task_id
    )
    result = await db.execute(task_query)
    task = result.scalar_one_or_none()
    
    if not task:
        return RedirectResponse(url="/ui/tasks", status_code=303)
    
    try:
        # Parse related_entity_id as UUID if provided
        entity_id = None
        if related_entity_id and related_entity_id.strip():
            try:
                entity_id = UUID(related_entity_id)
            except ValueError:
                return templates.TemplateResponse(
                    "task_form.html",
                    {
                        "request": request,
                        "current_user": current_user,
                        "active_page": "tasks",
                        "mode": "edit",
                        "task": task,
                        "error": "Invalid entity ID format",
                    },
                    status_code=400
                )
        
        # Parse date if provided
        parsed_due_date = None
        if due_date:
            from datetime import datetime
            parsed_due_date = datetime.fromisoformat(due_date)
        
        # Update task
        task_update_data = TaskUpdate(
            title=title.strip() if title else task.title,
            description=description.strip() if description else None,
            related_entity_type=related_entity_type if related_entity_type else None,
            related_entity_id=entity_id,
            due_date=parsed_due_date,
            status=status,
            assigned_to_user=assigned_to_user.strip() if assigned_to_user else None,
            completed_at=datetime.utcnow() if status == "completed" and task.status != "completed" else task.completed_at,
        )
        
        task_repo = TaskRepository(db)
        await task_repo.update(str(current_user.tenant_id), task_id, task_update_data)
        await db.commit()
        
        return RedirectResponse(
            url=f"/ui/tasks?create_success=Task+updated+successfully",
            status_code=303
        )
    
    except Exception as e:
        return templates.TemplateResponse(
            "task_form.html",
            {
                "request": request,
                "current_user": current_user,
                "active_page": "tasks",
                "mode": "edit",
                "task": task,
                "error": f"Failed to update task: {str(e)}",
            },
            status_code=400
        )


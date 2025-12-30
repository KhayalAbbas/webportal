"""
Task router - API endpoints for tasks.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_tenant_id
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=List[TaskRead])
async def list_tasks(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    assigned_to_user: Optional[str] = None,
    due_date_from: Optional[datetime] = None,
    due_date_to: Optional[datetime] = None,
):
    """
    List tasks with pagination and filters.
    
    Filters: status, assigned_to_user, due_date_from, due_date_to.
    """
    service = TaskService(db)
    tasks = await service.list_tasks(
        tenant_id=tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        assigned_to_user=assigned_to_user,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
    )
    return tasks


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get a task by ID."""
    service = TaskService(db)
    task = await service.get_task(tenant_id, task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found for this tenant"
        )
    
    return task


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new task."""
    service = TaskService(db)
    task = await service.create_task(tenant_id, data)
    await db.commit()
    return task


@router.put("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: UUID,
    data: TaskUpdate,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a task."""
    service = TaskService(db)
    task = await service.update_task(tenant_id, task_id, data)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found for this tenant"
        )
    
    await db.commit()
    return task

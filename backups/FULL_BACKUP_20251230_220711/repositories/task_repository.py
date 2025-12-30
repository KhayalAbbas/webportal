"""
Task repository - database operations for Task.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate


class TaskRepository:
    """Repository for Task database operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        assigned_to_user: Optional[str] = None,
        due_date_from: Optional[datetime] = None,
        due_date_to: Optional[datetime] = None,
    ) -> List[Task]:
        """List tasks for a tenant with filters."""
        query = select(Task).where(Task.tenant_id == tenant_id)
        
        if status is not None:
            query = query.where(Task.status == status)
        if assigned_to_user is not None:
            query = query.where(Task.assigned_to_user == assigned_to_user)
        if due_date_from is not None:
            query = query.where(Task.due_date >= due_date_from)
        if due_date_to is not None:
            query = query.where(Task.due_date <= due_date_to)
        
        query = query.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_by_id(self, tenant_id: str, task_id: UUID) -> Optional[Task]:
        """Get a task by ID for a specific tenant."""
        result = await self.db.execute(
            select(Task).where(
                Task.id == task_id,
                Task.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()
    
    async def create(self, tenant_id: str, data: TaskCreate) -> Task:
        """Create a new task."""
        task = Task(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            **data.model_dump(exclude={'tenant_id'})
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task
    
    async def update(
        self,
        tenant_id: str,
        task_id: UUID,
        data: TaskUpdate
    ) -> Optional[Task]:
        """Update a task."""
        task = await self.get_by_id(tenant_id, task_id)
        if not task:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(task, field, value)
        
        task.updated_at = func.now()
        await self.db.flush()
        await self.db.refresh(task)
        return task

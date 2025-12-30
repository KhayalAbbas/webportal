"""
Task business logic service.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate
from app.repositories.task_repository import TaskRepository


class TaskService:
    """Service for task business logic."""
    
    def __init__(self, db: AsyncSession):
        self.repository = TaskRepository(db)
    
    async def list_tasks(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        assigned_to_user: Optional[str] = None,
        due_date_from: Optional[datetime] = None,
        due_date_to: Optional[datetime] = None,
    ) -> List[Task]:
        """List tasks with filters."""
        return await self.repository.list(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            status=status,
            assigned_to_user=assigned_to_user,
            due_date_from=due_date_from,
            due_date_to=due_date_to,
        )
    
    async def get_task(self, tenant_id: str, task_id: UUID) -> Optional[Task]:
        """Get a task by ID."""
        return await self.repository.get_by_id(tenant_id, task_id)
    
    async def create_task(self, tenant_id: str, data: TaskCreate) -> Task:
        """Create a new task."""
        return await self.repository.create(tenant_id, data)
    
    async def update_task(
        self,
        tenant_id: str,
        task_id: UUID,
        data: TaskUpdate
    ) -> Optional[Task]:
        """Update a task."""
        return await self.repository.update(tenant_id, task_id, data)

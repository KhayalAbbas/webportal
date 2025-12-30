"""
CandidateAssignment Pydantic schemas.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class CandidateAssignmentCreate(TenantScopedBase):
    """Schema for creating a new candidate assignment."""
    
    candidate_id: UUID
    role_id: UUID
    status: Optional[str] = None
    is_hot: bool = False
    date_entered: Optional[str] = None
    start_date: Optional[str] = None
    current_stage_id: Optional[UUID] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class CandidateAssignmentUpdate(BaseModel):
    """Schema for updating a candidate assignment. All fields optional."""
    
    status: Optional[str] = None
    is_hot: Optional[bool] = None
    date_entered: Optional[str] = None
    start_date: Optional[str] = None
    current_stage_id: Optional[UUID] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class CandidateAssignmentRead(TenantScopedRead):
    """Schema for reading candidate assignment data (API response)."""
    
    candidate_id: UUID
    role_id: UUID
    status: Optional[str] = None
    is_hot: bool
    date_entered: Optional[str] = None
    start_date: Optional[str] = None
    current_stage_id: Optional[UUID] = None
    source: Optional[str] = None
    notes: Optional[str] = None

"""
AssessmentResult Pydantic schemas.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class AssessmentResultCreate(TenantScopedBase):
    """Schema for creating a new assessment result."""
    
    candidate_id: UUID
    role_id: Optional[UUID] = None
    assessment_type: str
    provider: Optional[str] = None
    score_numeric: Optional[int] = None
    score_label: Optional[str] = None
    payload: Optional[dict] = None
    taken_at: Optional[str] = None


class AssessmentResultUpdate(BaseModel):
    """Schema for updating an assessment result. All fields optional."""
    
    assessment_type: Optional[str] = None
    provider: Optional[str] = None
    score_numeric: Optional[int] = None
    score_label: Optional[str] = None
    payload: Optional[dict] = None
    taken_at: Optional[str] = None


class AssessmentResultRead(TenantScopedRead):
    """Schema for reading assessment result data (API response)."""
    
    candidate_id: UUID
    role_id: Optional[UUID] = None
    assessment_type: str
    provider: Optional[str] = None
    score_numeric: Optional[int] = None
    score_label: Optional[str] = None
    payload: Optional[dict] = None
    taken_at: Optional[str] = None

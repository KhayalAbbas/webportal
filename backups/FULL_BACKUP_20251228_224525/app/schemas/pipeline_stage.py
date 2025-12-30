"""
PipelineStage Pydantic schemas.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class PipelineStageCreate(TenantScopedBase):
    """Schema for creating a new pipeline stage."""
    
    code: str
    name: str
    order_index: int = 0


class PipelineStageUpdate(BaseModel):
    """Schema for updating a pipeline stage. All fields optional."""
    
    code: Optional[str] = None
    name: Optional[str] = None
    order_index: Optional[int] = None


class PipelineStageRead(TenantScopedRead):
    """Schema for reading pipeline stage data (API response)."""
    
    code: str
    name: str
    order_index: int

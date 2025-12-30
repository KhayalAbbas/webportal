"""
PipelineStage model.

Represents a stage in the recruitment pipeline (e.g., Sourced, Interview, Offer).
"""

from typing import Optional

from sqlalchemy import String, Integer

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class PipelineStage(TenantScopedModel):
    """
    PipelineStage table - represents a step in the recruitment process.
    
    Each tenant can customize their pipeline stages.
    The order_index determines the display order.
    """
    
    __tablename__ = "pipeline_stage"
    
    # Unique code for this stage (e.g., "SOURCED", "INTERVIEW_1")
    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    # Human-readable name (e.g., "Sourced", "First Interview")
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Order in the pipeline (1, 2, 3, etc.)
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

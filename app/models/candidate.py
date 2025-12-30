"""
Candidate model.

Represents a job candidate being tracked in the ATS.
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.activity_log import ActivityLog


class Candidate(TenantScopedModel):
    """
    Candidate table - represents a job seeker/candidate.
    
    Contains their personal info, current job details, CV, etc.
    """
    
    __tablename__ = "candidate"
    
    # Candidate's name
    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    
    # Contact information
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    mobile_1: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    mobile_2: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    phone_3: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    email_1: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    email_2: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    email_3: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Profile fields
    postal_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    
    home_country: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    
    marital_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    children_count: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )
    
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Current job info
    current_title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
    )
    
    current_company: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Location
    location: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # LinkedIn profile URL
    linkedin_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Full CV/resume text (for searching)
    cv_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Tags as comma-separated values (e.g., "python,aws,senior")
    tags: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Career / education fields
    salary_details: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    education_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    certifications: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    qualifications: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    languages: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Religion / social / bio fields
    religious_holidays: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    social_links: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    bio: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Assessment summary fields
    promotability_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    gamification_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    technical_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    last_psychometric_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assessment_result.id"),
        nullable=True,
    )
    
    # Activity logs for this candidate
    activity_logs: Mapped[List["ActivityLog"]] = relationship(
        "ActivityLog",
        back_populates="candidate",
        lazy="selectin",
    )

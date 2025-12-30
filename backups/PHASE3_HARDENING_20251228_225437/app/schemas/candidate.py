"""
Candidate Pydantic schemas.
"""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.base import TenantScopedBase, TenantScopedRead


class CandidateCreate(TenantScopedBase):
    """Schema for creating a new candidate."""
    
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_1: Optional[str] = None
    mobile_2: Optional[str] = None
    phone_3: Optional[str] = None
    email_1: Optional[str] = None
    email_2: Optional[str] = None
    email_3: Optional[str] = None
    postal_code: Optional[str] = None
    home_country: Optional[str] = None
    marital_status: Optional[str] = None
    children_count: Optional[int] = None
    date_of_birth: Optional[datetime] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    cv_text: Optional[str] = None
    tags: Optional[str] = None
    salary_details: Optional[str] = None
    education_summary: Optional[str] = None
    certifications: Optional[str] = None
    qualifications: Optional[str] = None
    languages: Optional[str] = None
    religious_holidays: Optional[str] = None
    social_links: Optional[dict] = None
    bio: Optional[str] = None
    promotability_score: Optional[int] = None
    gamification_score: Optional[int] = None
    technical_score: Optional[int] = None
    last_psychometric_result_id: Optional[str] = None


class CandidateUpdate(BaseModel):
    """Schema for updating a candidate. All fields optional."""
    
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_1: Optional[str] = None
    mobile_2: Optional[str] = None
    phone_3: Optional[str] = None
    email_1: Optional[str] = None
    email_2: Optional[str] = None
    email_3: Optional[str] = None
    postal_code: Optional[str] = None
    home_country: Optional[str] = None
    marital_status: Optional[str] = None
    children_count: Optional[int] = None
    date_of_birth: Optional[datetime] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    cv_text: Optional[str] = None
    tags: Optional[str] = None
    salary_details: Optional[str] = None
    education_summary: Optional[str] = None
    certifications: Optional[str] = None
    qualifications: Optional[str] = None
    languages: Optional[str] = None
    religious_holidays: Optional[str] = None
    social_links: Optional[dict] = None
    bio: Optional[str] = None
    promotability_score: Optional[int] = None
    gamification_score: Optional[int] = None
    technical_score: Optional[int] = None
    last_psychometric_result_id: Optional[str] = None


class CandidateRead(TenantScopedRead):
    """Schema for reading candidate data (API response)."""
    
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_1: Optional[str] = None
    mobile_2: Optional[str] = None
    phone_3: Optional[str] = None
    email_1: Optional[str] = None
    email_2: Optional[str] = None
    email_3: Optional[str] = None
    postal_code: Optional[str] = None
    home_country: Optional[str] = None
    marital_status: Optional[str] = None
    children_count: Optional[int] = None
    date_of_birth: Optional[datetime] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    cv_text: Optional[str] = None
    tags: Optional[str] = None
    salary_details: Optional[str] = None
    education_summary: Optional[str] = None
    certifications: Optional[str] = None
    qualifications: Optional[str] = None
    languages: Optional[str] = None
    religious_holidays: Optional[str] = None
    social_links: Optional[dict] = None
    bio: Optional[str] = None
    promotability_score: Optional[int] = None
    gamification_score: Optional[int] = None
    technical_score: Optional[int] = None
    last_psychometric_result_id: Optional[str] = None

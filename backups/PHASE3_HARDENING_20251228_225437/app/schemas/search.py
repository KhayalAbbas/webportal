"""
Search schemas.

Defines input/output schemas for search operations.
"""

from typing import Optional, List
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CandidateSearchResult(BaseModel):
    """
    Lightweight search result for a single candidate.
    
    This schema is designed for search results and excludes heavy fields
    like full CV text, detailed activity logs, etc.
    """
    
    model_config = ConfigDict(from_attributes=True)
    
    # Identity
    id: UUID
    first_name: str
    last_name: str
    
    # Current position
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    
    # Location
    location: Optional[str] = None
    home_country: Optional[str] = None
    
    # Skills and attributes
    languages: Optional[str] = None
    tags: Optional[str] = None
    
    # Scores
    promotability_score: Optional[int] = None
    technical_score: Optional[int] = None
    gamification_score: Optional[int] = None
    
    # Contact
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    
    # Bio snippet (first 300 chars of bio)
    bio_snippet: Optional[str] = None
    
    # Assignment info (populated when filtering by assignment_role_id)
    assignment_status: Optional[str] = None
    assignment_is_hot: Optional[bool] = None
    
    # Metadata
    created_at: datetime
    updated_at: datetime


class CandidateSearchResponse(BaseModel):
    """
    Paginated response envelope for candidate search results.
    """
    
    items: List[CandidateSearchResult]
    total: int
    limit: int
    offset: int

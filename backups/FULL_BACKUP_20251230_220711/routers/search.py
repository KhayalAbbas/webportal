"""
Search router.

Endpoints for searching candidates.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, verify_user_tenant_access
from app.models.user import User
from app.schemas.search import CandidateSearchResponse
from app.services.search_service import SearchService


router = APIRouter(
    prefix="/search",
    tags=["search"],
)


@router.get(
    "/candidates",
    response_model=CandidateSearchResponse,
    summary="Search candidates",
    description="""
Search for candidates in your database with full-text search and structured filters.

**Full-text search (q parameter):**
- Searches across: first_name, last_name, current_title, current_company, bio, tags, cv_text
- Uses PostgreSQL full-text search with relevance ranking
- Results are ranked by: relevance score, promotability_score, updated_at

**Structured filters (all optional):**
- home_country, location, current_title, current_company: Partial match (case-insensitive)
- languages: Partial match for language names
- promotability_min/max: Filter by promotability score range
- assignment_role_id: Only return candidates assigned to this role
- assignment_status: Filter by assignment status (requires assignment_role_id)

**Default ordering (when no text search):**
- promotability_score DESC (nulls last)
- updated_at DESC

**Pagination:**
- Default limit: 50
- Max limit: 200
- Use offset for pagination
""",
)
async def search_candidates(
    current_user: User = Depends(verify_user_tenant_access),
    session: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(
        None,
        description="Free-text search query (searches name, title, company, bio, tags, CV)",
        example="senior python aws"
    ),
    home_country: Optional[str] = Query(
        None,
        description="Filter by home country (partial match)",
        example="United States"
    ),
    location: Optional[str] = Query(
        None,
        description="Filter by location (partial match)",
        example="London"
    ),
    current_title: Optional[str] = Query(
        None,
        description="Filter by current title (partial match)",
        example="Director"
    ),
    current_company: Optional[str] = Query(
        None,
        description="Filter by current company (partial match)",
        example="Google"
    ),
    languages: Optional[str] = Query(
        None,
        description="Filter by languages (partial match)",
        example="English"
    ),
    promotability_min: Optional[int] = Query(
        None,
        description="Minimum promotability score",
        ge=0,
        le=100,
        example=70
    ),
    promotability_max: Optional[int] = Query(
        None,
        description="Maximum promotability score",
        ge=0,
        le=100,
        example=90
    ),
    assignment_role_id: Optional[UUID] = Query(
        None,
        description="Filter by candidates assigned to this role (UUID)",
        example="123e4567-e89b-12d3-a456-426614174000"
    ),
    assignment_status: Optional[str] = Query(
        None,
        description="Filter by assignment status (requires assignment_role_id)",
        example="SHORT_LIST"
    ),
    limit: int = Query(
        50,
        description="Number of results per page",
        ge=1,
        le=200,
        example=50
    ),
    offset: int = Query(
        0,
        description="Number of results to skip (for pagination)",
        ge=0,
        example=0
    ),
) -> CandidateSearchResponse:
    """
    Search for candidates with full-text search and structured filters.
    
    Requires JWT authentication and X-Tenant-ID header.
    Results are filtered by tenant_id automatically.
    """
    
    service = SearchService(session)
    
    return await service.search_candidates(
        tenant_id=current_user.tenant_id,
        q=q,
        home_country=home_country,
        location=location,
        current_title=current_title,
        current_company=current_company,
        languages=languages,
        promotability_min=promotability_min,
        promotability_max=promotability_max,
        assignment_role_id=assignment_role_id,
        assignment_status=assignment_status,
        limit=limit,
        offset=offset,
    )

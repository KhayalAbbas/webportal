"""
Search service.

Business logic for search operations.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.search_repository import SearchRepository
from app.schemas.search import CandidateSearchResult, CandidateSearchResponse


class SearchService:
    """Service for candidate search operations."""
    
    def __init__(self, session: AsyncSession):
        self.repository = SearchRepository(session)
    
    async def search_candidates(
        self,
        tenant_id: UUID,
        q: Optional[str] = None,
        home_country: Optional[str] = None,
        location: Optional[str] = None,
        current_title: Optional[str] = None,
        current_company: Optional[str] = None,
        languages: Optional[str] = None,
        promotability_min: Optional[int] = None,
        promotability_max: Optional[int] = None,
        assignment_role_id: Optional[UUID] = None,
        assignment_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CandidateSearchResponse:
        """
        Search candidates with full-text and structured filters.
        
        Returns a paginated response with search results.
        """
        
        # Validate and cap limit
        if limit <= 0:
            limit = 50
        elif limit > 200:
            limit = 200
        
        # Call repository
        candidates, total, assignments = await self.repository.search_candidates(
            tenant_id=tenant_id,
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
        
        # Convert to result schemas
        items = []
        for i, candidate in enumerate(candidates):
            assignment = assignments[i]
            
            # Create bio snippet (first 300 characters)
            bio_snippet = None
            if candidate.bio:
                bio_snippet = candidate.bio[:300]
                if len(candidate.bio) > 300:
                    bio_snippet += "..."
            
            result = CandidateSearchResult(
                id=candidate.id,
                first_name=candidate.first_name,
                last_name=candidate.last_name,
                current_title=candidate.current_title,
                current_company=candidate.current_company,
                location=candidate.location,
                home_country=candidate.home_country,
                languages=candidate.languages,
                tags=candidate.tags,
                promotability_score=candidate.promotability_score,
                technical_score=candidate.technical_score,
                gamification_score=candidate.gamification_score,
                email=candidate.email,
                phone=candidate.phone,
                linkedin_url=candidate.linkedin_url,
                bio_snippet=bio_snippet,
                assignment_status=assignment.status if assignment else None,
                assignment_is_hot=assignment.is_hot if assignment else None,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
            items.append(result)
        
        return CandidateSearchResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

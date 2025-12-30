"""
Search repository.

Database access layer for search operations.
"""

from typing import Optional, List, Tuple
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.candidate_assignment import CandidateAssignment


class SearchRepository:
    """Repository for candidate search operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
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
    ) -> Tuple[List[Candidate], int, List[Optional[CandidateAssignment]]]:
        """
        Search candidates with full-text search and structured filters.
        
        Returns:
            Tuple of (candidates, total_count, assignment_info_list)
            - candidates: List of Candidate models matching the search
            - total_count: Total number of matches (for pagination)
            - assignment_info_list: List of CandidateAssignment objects (or None) 
              corresponding to each candidate, only populated if assignment_role_id is provided
        
        Ranking logic:
            - If q is present: sort by text relevance, then promotability_score DESC, then updated_at DESC
            - If q is not present: sort by promotability_score DESC, then updated_at DESC
        """
        
        # Build the base query
        if assignment_role_id:
            # Join with CandidateAssignment when filtering by role
            query = (
                select(Candidate, CandidateAssignment)
                .join(
                    CandidateAssignment,
                    and_(
                        CandidateAssignment.candidate_id == Candidate.id,
                        CandidateAssignment.tenant_id == tenant_id,
                        CandidateAssignment.role_id == assignment_role_id,
                    )
                )
                .where(Candidate.tenant_id == tenant_id)
            )
            
            # If assignment_status is also provided, filter by it
            if assignment_status:
                query = query.where(CandidateAssignment.status == assignment_status)
        else:
            # No assignment filtering, just select candidates
            query = select(Candidate).where(Candidate.tenant_id == tenant_id)
        
        # Apply full-text search if q is provided
        if q and q.strip():
            # Use PostgreSQL's full-text search with the search_vector column
            # to_tsquery requires properly formatted query (words separated by &, |, etc.)
            # We'll use plainto_tsquery which is more forgiving for natural language
            search_condition = text(
                "search_vector @@ plainto_tsquery('english', :search_query)"
            ).bindparams(search_query=q.strip())
            
            if assignment_role_id:
                query = query.where(search_condition)
            else:
                query = query.where(search_condition)
        
        # Apply structured filters
        filters = []
        
        if home_country:
            filters.append(Candidate.home_country.ilike(f"%{home_country}%"))
        
        if location:
            filters.append(Candidate.location.ilike(f"%{location}%"))
        
        if current_title:
            filters.append(Candidate.current_title.ilike(f"%{current_title}%"))
        
        if current_company:
            filters.append(Candidate.current_company.ilike(f"%{current_company}%"))
        
        if languages:
            filters.append(Candidate.languages.ilike(f"%{languages}%"))
        
        if promotability_min is not None:
            filters.append(Candidate.promotability_score >= promotability_min)
        
        if promotability_max is not None:
            filters.append(Candidate.promotability_score <= promotability_max)
        
        if filters:
            query = query.where(and_(*filters))
        
        # Count total results (before pagination)
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0
        
        # Apply ordering
        if q and q.strip():
            # Order by relevance (using ts_rank), then promotability, then updated_at
            # ts_rank returns a relevance score for the full-text match
            rank_expr = text(
                "ts_rank(search_vector, plainto_tsquery('english', :search_query))"
            ).bindparams(search_query=q.strip())
            
            query = query.order_by(
                rank_expr.desc(),
                Candidate.promotability_score.desc().nulls_last(),
                Candidate.updated_at.desc()
            )
        else:
            # No text search, just order by promotability and recency
            query = query.order_by(
                Candidate.promotability_score.desc().nulls_last(),
                Candidate.updated_at.desc()
            )
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        # Execute query
        result = await self.session.execute(query)
        
        # Extract results
        if assignment_role_id:
            # We have tuples of (Candidate, CandidateAssignment)
            rows = result.all()
            candidates = [row[0] for row in rows]
            assignments = [row[1] for row in rows]
        else:
            # We have just Candidate objects
            candidates = list(result.scalars().all())
            assignments = [None] * len(candidates)
        
        return candidates, total, assignments

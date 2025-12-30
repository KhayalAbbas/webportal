"""
Schemas for combined research data responses.
"""

from typing import List
from pydantic import BaseModel

from app.schemas.research_event import ResearchEventRead
from app.schemas.source_document import SourceDocumentRead
from app.schemas.ai_enrichment import AIEnrichmentRead


class EntityResearchData(BaseModel):
    """Combined research data for an entity (candidate, company, or role)."""
    
    research_events: List[ResearchEventRead]
    source_documents: List[SourceDocumentRead]
    ai_enrichments: List[AIEnrichmentRead]

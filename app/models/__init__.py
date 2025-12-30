"""
Models package.

Import all models here so they are registered with SQLAlchemy.
This file also makes it easy to import models from one place.
"""

from app.models.tenant import Tenant
from app.models.user import User
from app.models.company import Company
from app.models.contact import Contact
from app.models.candidate import Candidate
from app.models.role import Role
from app.models.pipeline_stage import PipelineStage
from app.models.activity_log import ActivityLog
from app.models.research_event import ResearchEvent
from app.models.source_document import SourceDocument
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.models.candidate_assignment import CandidateAssignment
from app.models.assessment_result import AssessmentResult
from app.models.task import Task
from app.models.list import List
from app.models.list_item import ListItem
from app.models.bd_opportunity import BDOpportunity
from app.models.research_run import ResearchRun, ResearchRunStep
from app.models.research_run_bundle import ResearchRunBundle
from app.models.research_job import ResearchJob
from app.models.company_research import CompanyResearchRun

# Export all models
__all__ = [
    "Tenant",
    "User",
    "Company",
    "Contact",
    "Candidate",
    "Role",
    "PipelineStage",
    "ActivityLog",
    "ResearchEvent",
    "SourceDocument",
    "AIEnrichmentRecord",
    "CandidateAssignment",
    "AssessmentResult",
    "Task",
    "List",
    "ListItem",
    "BDOpportunity",
    "ResearchRun",
    "ResearchRunStep", 
    "ResearchRunBundle",
    "ResearchJob",
    "CompanyResearchRun",
]

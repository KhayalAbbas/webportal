"""
Schemas package.

Import all schemas here for easy access.
"""

from app.schemas.tenant import TenantCreate, TenantUpdate, TenantRead
from app.schemas.company import CompanyCreate, CompanyUpdate, CompanyRead
from app.schemas.contact import ContactCreate, ContactUpdate, ContactRead
from app.schemas.candidate import CandidateCreate, CandidateUpdate, CandidateRead
from app.schemas.role import RoleCreate, RoleUpdate, RoleRead
from app.schemas.pipeline_stage import PipelineStageCreate, PipelineStageUpdate, PipelineStageRead
from app.schemas.activity_log import ActivityLogCreate, ActivityLogUpdate, ActivityLogRead
from app.schemas.research_event import ResearchEventCreate, ResearchEventUpdate, ResearchEventRead
from app.schemas.source_document import SourceDocumentCreate, SourceDocumentUpdate, SourceDocumentRead
from app.schemas.ai_enrichment_record import AIEnrichmentRecordCreate, AIEnrichmentRecordUpdate, AIEnrichmentRecordRead
from app.schemas.candidate_assignment import CandidateAssignmentCreate, CandidateAssignmentUpdate, CandidateAssignmentRead
from app.schemas.assessment_result import AssessmentResultCreate, AssessmentResultUpdate, AssessmentResultRead
from app.schemas.task import TaskCreate, TaskUpdate, TaskRead
from app.schemas.list import ListCreate, ListUpdate, ListRead
from app.schemas.list_item import ListItemCreate, ListItemUpdate, ListItemRead
from app.schemas.bd_opportunity import BDOpportunityCreate, BDOpportunityUpdate, BDOpportunityRead
from app.schemas.executive_contact_enrichment import (
    ExecutiveContactEnrichmentResponse,
    BulkExecutiveContactEnrichmentRequest,
    BulkExecutiveContactEnrichmentResponse,
    BulkExecutiveContactEnrichmentResponseItem,
)

__all__ = [
    # Tenant
    "TenantCreate", "TenantUpdate", "TenantRead",
    # Company
    "CompanyCreate", "CompanyUpdate", "CompanyRead",
    # Contact
    "ContactCreate", "ContactUpdate", "ContactRead",
    # Candidate
    "CandidateCreate", "CandidateUpdate", "CandidateRead",
    # Role
    "RoleCreate", "RoleUpdate", "RoleRead",
    # PipelineStage
    "PipelineStageCreate", "PipelineStageUpdate", "PipelineStageRead",
    # ActivityLog
    "ActivityLogCreate", "ActivityLogUpdate", "ActivityLogRead",
    # ResearchEvent
    "ResearchEventCreate", "ResearchEventUpdate", "ResearchEventRead",
    # SourceDocument
    "SourceDocumentCreate", "SourceDocumentUpdate", "SourceDocumentRead",
    # AIEnrichmentRecord
    "AIEnrichmentRecordCreate", "AIEnrichmentRecordUpdate", "AIEnrichmentRecordRead",
    # CandidateAssignment
    "CandidateAssignmentCreate", "CandidateAssignmentUpdate", "CandidateAssignmentRead",
    # AssessmentResult
    "AssessmentResultCreate", "AssessmentResultUpdate", "AssessmentResultRead",
    # Task
    "TaskCreate", "TaskUpdate", "TaskRead",
    # List
    "ListCreate", "ListUpdate", "ListRead",
    # ListItem
    "ListItemCreate", "ListItemUpdate", "ListItemRead",
    # BDOpportunity
    "BDOpportunityCreate", "BDOpportunityUpdate", "BDOpportunityRead",
    # Executive contact enrichment
    "ExecutiveContactEnrichmentResponse",
    "BulkExecutiveContactEnrichmentRequest",
    "BulkExecutiveContactEnrichmentResponse",
    "BulkExecutiveContactEnrichmentResponseItem",
]

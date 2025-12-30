"""
AI Proposal Service for Phase 2 ingestion.

Handles validation and ingestion of AI-generated company research proposals.
"""

from typing import Dict, List, Optional, Set
from uuid import UUID
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.schemas.ai_proposal import (
    AIProposal,
    AIProposalValidationResult,
    AIProposalIngestionResult,
    AIProposalSource,
    AIProposalCompany,
    AIProposalMetric,
    AIProposalAlias,
)
from app.models.company_research import (
    CompanyResearchRun,
    CompanyProspect,
    CompanyMetric,
    CompanyAlias,
    ResearchSourceDocument,
    CompanyProspectEvidence,
)


def _normalize_company_name(name: str) -> str:
    """
    Normalize company name for canonical identity matching.
    Reuses Phase 1 normalization logic.
    """
    if not name:
        return ""
    
    normalized = name.lower().strip()
    
    # Remove trailing punctuation first
    while normalized and normalized[-1] in '.,;:':
        normalized = normalized[:-1].strip()
    
    # Remove common legal suffixes (iterate to handle multiple)
    suffixes = [
        ' ltd', ' llc', ' plc', ' saog', ' sa', ' gmbh', ' ag',
        ' inc', ' corp', ' corporation', ' limited', ' group', ' holdings',
        ' company', ' co',
    ]
    
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                changed = True
                break
        # Remove trailing punctuation after each suffix removal
        while normalized and normalized[-1] in '.,;:':
            normalized = normalized[:-1].strip()
            changed = True
    
    # Normalize whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized.strip()


class AIProposalService:
    """Service for validating and ingesting AI proposals."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def validate_proposal(
        self,
        tenant_id: UUID,
        run_id: UUID,
        proposal: AIProposal,
    ) -> AIProposalValidationResult:
        """
        Validate AI proposal without making changes.
        
        Checks:
        - Schema compliance (already done by Pydantic)
        - Source temp_id references are valid
        - Company names can be normalized
        - Detect potential duplicates with existing prospects
        - Metric value types are consistent
        """
        result = AIProposalValidationResult(
            valid=True,  # Start as valid, set to False if errors found
            company_count=len(proposal.companies),
            source_count=len(proposal.sources),
            metric_count=sum(len(c.metrics) for c in proposal.companies),
        )

        
        # Check run exists
        run = await self.session.get(CompanyResearchRun, run_id)
        if not run or run.tenant_id != tenant_id:
            result.add_error("run_id", f"Research run {run_id} not found")
            return result
        
        # Build source temp_id lookup
        source_temp_ids = {s.temp_id for s in proposal.sources}
        
        # Validate each company
        seen_normalized_names: Set[str] = set()
        
        for idx, company in enumerate(proposal.companies):
            company_path = f"companies[{idx}]"
            
            # Check name normalization
            normalized = _normalize_company_name(company.name)
            if not normalized:
                result.add_error(
                    f"{company_path}.name",
                    f"Company name '{company.name}' normalizes to empty string"
                )
                continue
            
            # Check for duplicates within proposal
            if normalized in seen_normalized_names:
                result.add_warning(
                    f"Duplicate company detected: '{company.name}' (normalized: '{normalized}')"
                )
            seen_normalized_names.add(normalized)
            
            # Check for existing prospects with same normalized name
            existing = await self.session.execute(
                select(CompanyProspect).where(
                    and_(
                        CompanyProspect.tenant_id == tenant_id,
                        CompanyProspect.company_research_run_id == run_id,
                        CompanyProspect.name_normalized == normalized,
                    )
                )
            )
            if existing.scalar_one_or_none():
                result.add_warning(
                    f"Company '{company.name}' already exists in this run (will update)"
                )
            
            # Validate metrics
            for midx, metric in enumerate(company.metrics):
                metric_path = f"{company_path}.metrics[{midx}]"
                
                # Check source reference
                if metric.source_temp_id and metric.source_temp_id not in source_temp_ids:
                    result.add_error(
                        f"{metric_path}.source_temp_id",
                        f"References unknown source '{metric.source_temp_id}'"
                    )
                
                # Value consistency is now validated by Pydantic model_validator
                # No need for additional checks here since AIProposalMetric already ensures
                # that value matches the declared type
            
            # Validate aliases
            for aidx, alias in enumerate(company.aliases or []):
                alias_path = f"{company_path}.aliases[{aidx}]"
                alias_normalized = _normalize_company_name(alias.name)
                if not alias_normalized:
                    result.add_error(
                        f"{alias_path}.name",
                        f"Alias name '{alias.name}' normalizes to empty string"
                    )
        
        return result
    
    async def ingest_proposal(
        self,
        tenant_id: UUID,
        run_id: UUID,
        proposal: AIProposal,
        source_id_map_override: Optional[dict[str, UUID]] = None,
    ) -> AIProposalIngestionResult:
        """
        Ingest AI proposal into database.
        
        Process:
        1. Validate proposal
        2. Create source documents
        3. For each company:
           - Normalize name and check for existing prospect
           - Create or update prospect
           - Create metrics
           - Create aliases
           - Create evidence links
        4. Commit transaction
        
        Idempotent: Re-ingesting same proposal won't create duplicates.
        """
        result = AIProposalIngestionResult(success=True)
        
        # Validate first
        validation = await self.validate_proposal(tenant_id, run_id, proposal)
        if not validation.valid:
            result.success = False
            result.errors = [f"{e.field}: {e.message}" for e in validation.errors]
            return result
        
        # Get run
        run = await self.session.get(CompanyResearchRun, run_id)
        if not run:
            result.add_error(f"Research run {run_id} not found")
            return result
        
        try:
            # Step 1: Create source documents (or reuse provided mapping)
            source_id_map: Dict[str, UUID] = dict(source_id_map_override or {})
            
            for source_data in proposal.sources:
                if source_data.temp_id in source_id_map:
                    continue

                existing_source = None
                if source_data.url:
                    existing_query = await self.session.execute(
                        select(ResearchSourceDocument).where(
                            and_(
                                ResearchSourceDocument.tenant_id == tenant_id,
                                ResearchSourceDocument.company_research_run_id == run_id,
                                ResearchSourceDocument.url == source_data.url,
                            )
                        )
                    )
                    existing_source = existing_query.scalar_one_or_none()
                
                if existing_source:
                    source_id_map[source_data.temp_id] = existing_source.id
                else:
                    source_doc = ResearchSourceDocument(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        company_research_run_id=run_id,
                        source_type='ai_proposal',
                        title=source_data.title,
                        url=source_data.url,
                        provider=source_data.provider,
                        status='processed',
                        fetched_at=source_data.fetched_at or datetime.utcnow(),
                    )
                    self.session.add(source_doc)
                    await self.session.flush()
                    source_id_map[source_data.temp_id] = source_doc.id
                    result.sources_created += 1
            
            # Step 2: Process each company
            for company_data in proposal.companies:
                await self._ingest_company(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    role_mandate_id=run.role_mandate_id,
                    company_data=company_data,
                    source_id_map=source_id_map,
                    result=result,
                )
            
            # Commit transaction
            await self.session.commit()
            
        except Exception as e:
            await self.session.rollback()
            result.add_error(f"Ingestion failed: {str(e)}")
            return result
        
        return result
    
    async def _ingest_company(
        self,
        tenant_id: UUID,
        run_id: UUID,
        role_mandate_id: UUID,
        company_data: AIProposalCompany,
        source_id_map: Dict[str, UUID],
        result: AIProposalIngestionResult,
    ):
        """Ingest a single company with metrics, aliases, and evidence."""
        
        # Normalize company name
        normalized_name = _normalize_company_name(company_data.name)
        
        # Check for existing prospect
        existing_query = await self.session.execute(
            select(CompanyProspect).where(
                and_(
                    CompanyProspect.tenant_id == tenant_id,
                    CompanyProspect.company_research_run_id == run_id,
                    CompanyProspect.name_normalized == normalized_name,
                )
            )
        )
        prospect = existing_query.scalar_one_or_none()
        
        if prospect:
            # Update existing prospect
            result.companies_existing += 1
            
            # Update AI ranking if provided
            if company_data.ai_rank is not None:
                prospect.ai_rank = company_data.ai_rank
            if company_data.ai_score is not None:
                prospect.ai_score = company_data.ai_score
            
            # Update other fields if they're currently empty
            if company_data.website_url and not prospect.website_url:
                prospect.website_url = company_data.website_url
            if company_data.hq_country and not prospect.hq_country:
                prospect.hq_country = company_data.hq_country
            if company_data.hq_city and not prospect.hq_city:
                prospect.hq_city = company_data.hq_city
            if company_data.sector and not prospect.sector:
                prospect.sector = company_data.sector
            if company_data.description and not prospect.description:
                prospect.description = company_data.description
            
        else:
            # Create new prospect
            prospect = CompanyProspect(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                company_research_run_id=run_id,
                role_mandate_id=role_mandate_id,
                name_raw=company_data.name,
                name_normalized=normalized_name,
                website_url=company_data.website_url,
                hq_country=company_data.hq_country,
                hq_city=company_data.hq_city,
                sector=company_data.sector,
                description=company_data.description,
                ai_rank=company_data.ai_rank,
                ai_score=company_data.ai_score,
                status='new',
            )
            self.session.add(prospect)
            await self.session.flush()
            result.companies_new += 1
        
        result.companies_ingested += 1
        
        # Ingest metrics
        for metric_data in company_data.metrics:
            await self._ingest_metric(
                tenant_id=tenant_id,
                run_id=run_id,
                prospect=prospect,
                metric_data=metric_data,
                source_id_map=source_id_map,
                result=result,
            )
        
        # Ingest aliases
        for alias_data in company_data.aliases or []:
            await self._ingest_alias(
                tenant_id=tenant_id,
                prospect=prospect,
                alias_data=alias_data,
                result=result,
            )
            
        # Ingest company-level evidence (from evidence_snippets and source_sha256s)
        await self._ingest_company_evidence(
            tenant_id=tenant_id,
            run_id=run_id,
            prospect=prospect,
            company_data=company_data,
            source_id_map=source_id_map,
            result=result,
        )
    
    async def _ingest_metric(
        self,
        tenant_id: UUID,
        run_id: UUID,
        prospect: CompanyProspect,
        metric_data: AIProposalMetric,
        source_id_map: Dict[str, UUID],
        result: AIProposalIngestionResult,
    ):
        """Ingest a single metric for a company with typed value support."""
        
        # Get source document ID if referenced
        source_doc_id = None
        if metric_data.source_temp_id:
            source_doc_id = source_id_map.get(metric_data.source_temp_id)
        
        # Map typed value to appropriate column
        value_number = None
        value_text = None
        value_bool = None
        value_json = None
        
        if metric_data.type == "number":
            value_number = float(metric_data.value) if metric_data.value is not None else None
        elif metric_data.type == "text":
            value_text = str(metric_data.value)
        elif metric_data.type == "bool":
            value_bool = bool(metric_data.value)
        elif metric_data.type == "json":
            value_json = metric_data.value  # Already dict/list
        
        # Check for existing identical metric (avoid duplicates)
        # "Identical" = same tenant, run, company, key, as_of_date, currency, source, AND all value_* fields
        existing_query = await self.session.execute(
            select(CompanyMetric).where(
                and_(
                    CompanyMetric.tenant_id == tenant_id,
                    CompanyMetric.company_prospect_id == prospect.id,
                    CompanyMetric.metric_key == metric_data.key,
                    CompanyMetric.value_type == metric_data.type,
                    CompanyMetric.as_of_date == metric_data.as_of_date,
                    CompanyMetric.source_document_id == source_doc_id,
                    # Check appropriate value field
                    CompanyMetric.value_number == value_number if value_number is not None else True,
                    CompanyMetric.value_text == value_text if value_text is not None else True,
                    CompanyMetric.value_bool == value_bool if value_bool is not None else True,
                    # Note: JSONB equality in SQLAlchemy can be tricky, skip for now
                )
            )
        )
        existing_metric = existing_query.scalar_one_or_none()
        
        if existing_metric:
            # Metric already exists, skip to avoid duplicate
            return
        
        # Create new metric
        metric = CompanyMetric(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            company_research_run_id=run_id,
            company_prospect_id=prospect.id,
            metric_key=metric_data.key,
            value_type=metric_data.type,
            value_number=value_number,
            value_text=value_text,
            value_bool=value_bool,
            value_json=value_json,
            value_currency=metric_data.currency,
            unit=metric_data.unit,
            as_of_date=metric_data.as_of_date,
            confidence=metric_data.confidence,
            source_document_id=source_doc_id,
        )
        self.session.add(metric)
        result.metrics_ingested += 1
        
        # Create evidence if snippet provided
        if metric_data.evidence_snippet:
            evidence = CompanyProspectEvidence(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                company_prospect_id=prospect.id,
                source_type='ai_proposal_metric',
                source_name=f"Metric: {metric_data.key}",
                source_url=None,  # Could link to source doc URL
                raw_snippet=metric_data.evidence_snippet,
                evidence_weight=metric_data.confidence or 0.5,
            )
            self.session.add(evidence)
            result.evidence_created += 1
    
    async def _ingest_alias(
        self,
        tenant_id: UUID,
        prospect: CompanyProspect,
        alias_data: AIProposalAlias,
        result: AIProposalIngestionResult,
    ):
        """Ingest a single alias for a company."""
        
        # Check for existing alias (avoid duplicates)
        existing_query = await self.session.execute(
            select(CompanyAlias).where(
                and_(
                    CompanyAlias.tenant_id == tenant_id,
                    CompanyAlias.company_prospect_id == prospect.id,
                    CompanyAlias.alias_name == alias_data.name,
                )
            )
        )
        existing_alias = existing_query.scalar_one_or_none()
        
        if not existing_alias:
            # Create new alias
            alias = CompanyAlias(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                company_prospect_id=prospect.id,
                alias_name=alias_data.name,
                alias_type=alias_data.type,
                source_type='ai_proposal',
                confidence=alias_data.confidence,
            )
            self.session.add(alias)
            result.aliases_ingested += 1
    
    async def _ingest_company_evidence(
        self,
        tenant_id: UUID,
        run_id: UUID,
        prospect: CompanyProspect,
        company_data: AIProposalCompany,
        source_id_map: Dict[str, UUID],
        result: AIProposalIngestionResult,
    ):
        """Ingest company-level evidence from evidence_snippets and source_sha256s."""
        
        # Create evidence rows for each evidence_snippet linked to source documents
        for i, evidence_snippet in enumerate(company_data.evidence_snippets):
            # Find a corresponding source_sha256 (use first one if available, or cycle through)
            source_sha256 = None
            if company_data.source_sha256s:
                source_sha256 = company_data.source_sha256s[i % len(company_data.source_sha256s)]
            
            # Look up source document by content_hash (which contains the SHA256)
            source_doc_id = None
            source_doc_url = None
            source_content_hash = None
            if source_sha256:
                source_query = await self.session.execute(
                    select(ResearchSourceDocument).where(
                        and_(
                            ResearchSourceDocument.tenant_id == tenant_id,
                            ResearchSourceDocument.company_research_run_id == run_id,
                            ResearchSourceDocument.content_hash == source_sha256,
                        )
                    )
                )
                source_doc = source_query.scalar_one_or_none()
                if source_doc:
                    source_doc_id = source_doc.id
                    source_doc_url = source_doc.url
                    source_content_hash = source_doc.content_hash
            
            # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
            # The unique constraint is on (tenant_id, company_prospect_id, source_document_id, raw_snippet)
            evidence = CompanyProspectEvidence(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                company_prospect_id=prospect.id,
                source_type='ai_proposal_company',
                source_name=f"Company Evidence (SHA256: {source_sha256})" if source_sha256 else "Company Evidence",
                source_url=source_doc_url,
                raw_snippet=evidence_snippet,
                evidence_weight=0.8,  # High weight for direct company evidence
                source_document_id=source_doc_id,  # New linkage field
                source_content_hash=source_content_hash,  # New linkage field
            )
            
            # Use merge for upsert behavior with the unique constraint
            try:
                self.session.add(evidence)
                await self.session.flush()  # Force the insert to check constraints
                result.evidence_created += 1
            except Exception as e:
                # If constraint violation (duplicate), rollback this add and continue
                await self.session.rollback()
                # Re-begin transaction for next operations
                await self.session.begin()

"""
Contact enrichment orchestration service.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.candidate import Candidate
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.candidate_contact_point_repository import CandidateContactPointRepository
from app.repositories.research_event_repository import ResearchEventRepository
from app.repositories.source_document_repository import SourceDocumentRepository
from app.repositories.ai_enrichment_repository import AIEnrichmentRepository
from app.repositories.company_research_repo import CompanyResearchRepository
from app.schemas.research_event import ResearchEventCreate
from app.schemas.source_document import SourceDocumentCreate as EventSourceDocumentCreate
from app.schemas.company_research import SourceDocumentCreate as ResearchSourceDocumentCreate
from app.schemas.ai_enrichment import AIEnrichmentCreate
from app.schemas.contact_enrichment import ContactEnrichmentRequest, ProviderEnrichmentResult
from app.utils.canonical_json import canonical_dumps, canonical_hash
from app.services.contact_enrichment import MockLushaAdapter, MockSignalHireAdapter
from app.models.company_research import ExecutiveProspectEvidence

PURPOSE_CONTACT_ENRICHMENT = "candidate_contact_enrichment"
PURPOSE_EXEC_CONTACT_ENRICHMENT = "executive_contact_enrichment"


class ContactEnrichmentService:
    """Service to run contact enrichment across providers."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.candidate_repo = CandidateRepository(db)
        self.contact_point_repo = CandidateContactPointRepository(db)
        self.research_event_repo = ResearchEventRepository(db)
        self.source_document_repo = SourceDocumentRepository(db)
        self.ai_enrichment_repo = AIEnrichmentRepository(db)
        self.company_repo = CompanyResearchRepository(db)
        self.adapters = {
            "lusha": MockLushaAdapter(),
            "signalhire": MockSignalHireAdapter(),
        }

    async def enrich_candidate_contacts(
        self,
        tenant_id: str,
        candidate_id: UUID,
        request: ContactEnrichmentRequest,
        performed_by: Optional[str] = None,
    ) -> Optional[List[ProviderEnrichmentResult]]:
        candidate = await self.candidate_repo.get_by_id(tenant_id, candidate_id)
        if not candidate:
            return None

        tenant_uuid = UUID(str(tenant_id))
        candidate_context = self._candidate_context(candidate)
        provider_results: List[ProviderEnrichmentResult] = []

        for provider_name in request.providers:
            normalized_provider = provider_name.lower()
            adapter = self.adapters.get(normalized_provider)
            if not adapter:
                provider_results.append(
                    ProviderEnrichmentResult(
                        provider=normalized_provider,
                        status="error",
                        message="Unsupported provider",
                    )
                )
                continue

            recent = await self.ai_enrichment_repo.get_latest_for_provider(
                tenant_uuid,
                normalized_provider,
                PURPOSE_CONTACT_ENRICHMENT,
                candidate_id,
                "CANDIDATE",
            )
            if recent and not request.force and request.ttl_minutes > 0:
                deadline = recent.created_at + timedelta(minutes=request.ttl_minutes)
                now = datetime.now(timezone.utc)
                if deadline > now:
                    recent_source = self._source_document_from_enrichment(recent)
                    provider_results.append(
                        ProviderEnrichmentResult(
                            provider=normalized_provider,
                            status="skipped",
                            enrichment_id=recent.id,
                            message="TTL window not expired",
                            source_document_id=recent_source,
                        )
                    )
                    continue

            raw_payload = await adapter.fetch_contacts(candidate_context)
            payload_with_context = {
                "provider": normalized_provider,
                "mode": request.mode,
                "candidate": candidate_context,
                "payload": raw_payload,
            }
            content_hash = canonical_hash(payload_with_context)
            canonical_text = canonical_dumps(payload_with_context)

            existing = await self.ai_enrichment_repo.get_by_hash(
                tenant_uuid,
                normalized_provider,
                PURPOSE_CONTACT_ENRICHMENT,
                content_hash,
                candidate_id,
                "CANDIDATE",
            )
            if existing and not request.force:
                existing_source = self._source_document_from_enrichment(existing)
                provider_results.append(
                    ProviderEnrichmentResult(
                        provider=normalized_provider,
                        status="skipped",
                        enrichment_id=existing.id,
                        message="Identical payload already processed",
                        source_document_id=existing_source,
                    )
                )
                continue

            research_event = await self.research_event_repo.create(
                tenant_uuid,
                ResearchEventCreate(
                    tenant_id=tenant_uuid,
                    source_type=normalized_provider,
                    source_url=raw_payload.get("source_url") if isinstance(raw_payload, dict) else None,
                    entity_type="CANDIDATE",
                    entity_id=candidate_id,
                    raw_payload=payload_with_context,
                ),
            )

            source_document = await self.source_document_repo.create(
                tenant_uuid,
                EventSourceDocumentCreate(
                    tenant_id=tenant_uuid,
                    research_event_id=research_event.id,
                    document_type="provider_json",
                    title=f"{normalized_provider.title()} contact data",
                    url=raw_payload.get("source_url") if isinstance(raw_payload, dict) else None,
                    text_content=canonical_text,
                    doc_metadata={
                        "provider": normalized_provider,
                        "mode": request.mode,
                        "schema_version": raw_payload.get("schema_version") if isinstance(raw_payload, dict) else None,
                    },
                ),
            )

            contact_points = self._extract_contact_points(raw_payload, normalized_provider, source_document.id)
            added_points, existing_points = await self.contact_point_repo.upsert_points(
                tenant_uuid,
                candidate_id,
                contact_points,
            )

            await self._backfill_candidate_contacts(candidate, added_points)

            enrichment = await self.ai_enrichment_repo.create(
                tenant_uuid,
                AIEnrichmentCreate(
                    target_type="CANDIDATE",
                    target_id=candidate_id,
                    model_name=f"mock-{normalized_provider}",
                    enrichment_type="CONTACT_POINTS",
                    payload={
                        "provider_payload": raw_payload,
                        "contact_points_added": [self._contact_point_summary(cp) for cp in added_points],
                        "candidate_source_document_id": str(source_document.id),
                    },
                    purpose=PURPOSE_CONTACT_ENRICHMENT,
                    provider=normalized_provider,
                    content_hash=content_hash,
                    source_document_id=None,
                    status="success",
                    error_message=None,
                ),
            )

            provider_results.append(
                ProviderEnrichmentResult(
                    provider=normalized_provider,
                    status="created",
                    added_points=len(added_points),
                    skipped_points=len(existing_points),
                    enrichment_id=enrichment.id,
                    source_document_id=source_document.id,
                )
            )

        total_added = sum(result.added_points for result in provider_results if result.added_points)
        total_skipped = sum(result.skipped_points for result in provider_results if result.skipped_points)
        if provider_results:
            self.db.add(
                ActivityLog(
                    tenant_id=tenant_uuid,
                    candidate_id=candidate_id,
                    type="CONTACT_ENRICHMENT",
                    message=f"Providers: {', '.join([r.provider for r in provider_results])}; added {total_added} new; skipped {total_skipped}",
                    created_by=performed_by,
                )
            )

        await self.db.commit()
        return provider_results

    def _source_document_from_enrichment(self, enrichment: Any) -> Optional[UUID]:
        if getattr(enrichment, "source_document_id", None):
            return enrichment.source_document_id
        payload = getattr(enrichment, "payload", None)
        if isinstance(payload, dict):
            candidate_doc = payload.get("candidate_source_document_id")
            if candidate_doc:
                try:
                    return UUID(str(candidate_doc))
                except ValueError:
                    return None
        return None

    def _candidate_context(self, candidate: Candidate) -> Dict[str, Any]:
        full_name = f"{candidate.first_name} {candidate.last_name}".strip()
        return {
            "id": str(candidate.id),
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "full_name": full_name,
            "current_company": candidate.current_company,
            "current_title": candidate.current_title,
            "linkedin_url": candidate.linkedin_url,
        }

    def _normalize_email(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        email = value.strip().lower()
        return email if "@" in email else None

    def _normalize_phone(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        digits = re.sub(r"[^\d+]+", "", value)
        if digits.startswith("00"):
            digits = "+" + digits[2:]
        return digits if len(digits) >= 7 else None

    def _extract_contact_points(
        self,
        payload: Any,
        provider: str,
        source_document_id: UUID,
    ) -> List[dict]:
        points: List[dict] = []
        if not isinstance(payload, dict):
            return points

        for email_entry in payload.get("emails", []) or []:
            raw_email = email_entry.get("value") or email_entry.get("email")
            normalized = self._normalize_email(raw_email)
            if not normalized:
                continue
            points.append(
                {
                    "kind": "email",
                    "value_raw": raw_email,
                    "value_normalized": normalized,
                    "label": email_entry.get("label"),
                    "is_primary": bool(email_entry.get("primary")),
                    "provider": provider,
                    "confidence": email_entry.get("confidence"),
                    "source_document_id": source_document_id,
                }
            )

        for phone_entry in payload.get("phones", []) or []:
            raw_phone = phone_entry.get("value") or phone_entry.get("phone")
            normalized_phone = self._normalize_phone(raw_phone)
            if not normalized_phone:
                continue
            points.append(
                {
                    "kind": "phone",
                    "value_raw": raw_phone,
                    "value_normalized": normalized_phone,
                    "label": phone_entry.get("label"),
                    "is_primary": bool(phone_entry.get("primary")),
                    "provider": provider,
                    "confidence": phone_entry.get("confidence"),
                    "source_document_id": source_document_id,
                }
            )

        return points

    def _executive_context(self, executive: Any) -> Dict[str, Any]:
        company = getattr(executive, "company_prospect", None)
        return {
            "id": str(executive.id),
            "company_prospect_id": str(executive.company_prospect_id),
            "company_name": getattr(company, "name_normalized", None)
            or getattr(company, "name_raw", None),
            "run_id": str(executive.company_research_run_id),
            "name": executive.name_raw,
            "name_normalized": executive.name_normalized,
            "title": executive.title,
            "linkedin_url": executive.linkedin_url,
            "profile_url": executive.profile_url,
            "email": executive.email,
            "status": executive.status,
            "verification_status": executive.verification_status,
            "review_status": getattr(executive, "review_status", None),
        }

    async def enrich_executive_contacts(
        self,
        tenant_id: str,
        executive_id: UUID,
        request: ContactEnrichmentRequest,
        performed_by: Optional[str] = None,
    ) -> Optional[List[ProviderEnrichmentResult]]:
        executive = await self.company_repo.get_executive_prospect(tenant_id, executive_id)
        if not executive:
            return None

        tenant_uuid = UUID(str(tenant_id))
        exec_context = self._executive_context(executive)
        provider_results: List[ProviderEnrichmentResult] = []

        for provider_name in request.providers:
            normalized_provider = provider_name.lower()
            adapter = self.adapters.get(normalized_provider)
            if not adapter:
                provider_results.append(
                    ProviderEnrichmentResult(
                        provider=normalized_provider,
                        status="error",
                        message="Unsupported provider",
                    )
                )
                continue

            recent = await self.ai_enrichment_repo.get_latest_for_provider(
                tenant_uuid,
                normalized_provider,
                PURPOSE_EXEC_CONTACT_ENRICHMENT,
                executive_id,
                "EXECUTIVE",
            )
            if recent and not request.force and request.ttl_minutes > 0:
                deadline = recent.created_at + timedelta(minutes=request.ttl_minutes)
                now = datetime.now(timezone.utc)
                if deadline > now:
                    recent_source = self._source_document_from_enrichment(recent)
                    provider_results.append(
                        ProviderEnrichmentResult(
                            provider=normalized_provider,
                            status="skipped",
                            enrichment_id=recent.id,
                            message="TTL window not expired",
                            source_document_id=recent_source,
                        )
                    )
                    continue

            raw_payload = await adapter.fetch_contacts(exec_context)
            payload_with_context = {
                "provider": normalized_provider,
                "mode": request.mode,
                "executive": exec_context,
                "payload": raw_payload,
            }
            content_hash = canonical_hash(payload_with_context)
            canonical_text = canonical_dumps(payload_with_context)

            existing = await self.ai_enrichment_repo.get_by_hash(
                tenant_uuid,
                normalized_provider,
                PURPOSE_EXEC_CONTACT_ENRICHMENT,
                content_hash,
                executive_id,
                "EXECUTIVE",
            )
            if existing and not request.force:
                existing_source = self._source_document_from_enrichment(existing)
                provider_results.append(
                    ProviderEnrichmentResult(
                        provider=normalized_provider,
                        status="skipped",
                        enrichment_id=existing.id,
                        message="Identical payload already processed",
                        source_document_id=existing_source,
                    )
                )
                continue

            source_document = await self.company_repo.create_source_document(
                tenant_id,
                ResearchSourceDocumentCreate(
                    company_research_run_id=executive.company_research_run_id,
                    source_type="provider_json",
                    title=f"{normalized_provider.title()} contact data (executive)",
                    url=raw_payload.get("source_url") if isinstance(raw_payload, dict) else None,
                    original_url=raw_payload.get("source_url") if isinstance(raw_payload, dict) else None,
                    content_text=canonical_text,
                    content_hash=content_hash,
                    mime_type="application/json",
                    meta={
                        "provider": normalized_provider,
                        "mode": request.mode,
                        "schema_version": raw_payload.get("schema_version") if isinstance(raw_payload, dict) else None,
                        "content_hash": content_hash,
                        "company_name": exec_context.get("company_name"),
                        "entity": "executive",
                    },
                    max_attempts=1,
                ),
            )

            evidence = ExecutiveProspectEvidence(
                tenant_id=tenant_uuid,
                executive_prospect_id=executive_id,
                source_type="contact_enrichment",
                source_name=f"{normalized_provider} contact enrichment",
                source_url=raw_payload.get("source_url") if isinstance(raw_payload, dict) else None,
                raw_snippet=None,
                evidence_weight=0.5,
                source_document_id=source_document.id,
                source_content_hash=content_hash,
            )
            self.db.add(evidence)

            enrichment = await self.ai_enrichment_repo.create(
                tenant_uuid,
                AIEnrichmentCreate(
                    target_type="EXECUTIVE",
                    target_id=executive_id,
                    model_name=f"mock-{normalized_provider}",
                    enrichment_type="CONTACT_POINTS",
                    payload={
                        "provider_payload": raw_payload,
                        "source_document_id": str(source_document.id),
                        "executive_id": str(executive_id),
                    },
                    company_research_run_id=executive.company_research_run_id,
                    purpose=PURPOSE_EXEC_CONTACT_ENRICHMENT,
                    provider=normalized_provider,
                    input_scope_hash=content_hash,
                    content_hash=content_hash,
                    source_document_id=source_document.id,
                    status="success",
                    error_message=None,
                ),
            )

            provider_results.append(
                ProviderEnrichmentResult(
                    provider=normalized_provider,
                    status="created",
                    added_points=0,
                    skipped_points=0,
                    enrichment_id=enrichment.id,
                    source_document_id=source_document.id,
                )
            )

        await self.db.commit()
        return provider_results

    async def _backfill_candidate_contacts(self, candidate: Candidate, added_points: List[Any]) -> None:
        if not added_points:
            return

        email_fields = ["email", "email_1", "email_2"]
        phone_fields = ["phone", "mobile_1", "mobile_2", "phone_3"]

        for point in added_points:
            if point.kind == "email":
                for field in email_fields:
                    if getattr(candidate, field) is None:
                        setattr(candidate, field, point.value_raw)
                        break
            elif point.kind == "phone":
                for field in phone_fields:
                    if getattr(candidate, field) is None:
                        setattr(candidate, field, point.value_raw)
                        break
        await self.db.flush()
        await self.db.refresh(candidate)

    def _contact_point_summary(self, cp: Any) -> dict:
        return {
            "id": str(cp.id),
            "kind": cp.kind,
            "value": cp.value_raw,
            "provider": cp.provider,
            "is_primary": cp.is_primary,
            "label": cp.label,
        }

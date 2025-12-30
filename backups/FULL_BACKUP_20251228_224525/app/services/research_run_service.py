"""
Service for Phase 3 research run ledger and bundle acceptance.
"""

import hashlib
import json
import uuid
from typing import Dict, List, Tuple
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_research import ResearchSourceDocument, CompanyResearchRun
from app.models.research_run import ResearchRun
from app.repositories.research_run_repository import ResearchRunRepository
from app.schemas.research_run import (
    ResearchRunCreate,
    ResearchRunRead,
    ResearchRunWithCounts,
    RunBundleV1,
    BundleValidationError,
    BundleValidationResponse,
    BundleAcceptedResponse,
)
from app.schemas.ai_proposal import AIProposal
from app.services.ai_proposal_service import AIProposalService


def _canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ResearchRunService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ResearchRunRepository(db)

    async def create_run(self, tenant_id: UUID, data: ResearchRunCreate, created_by_user_id: UUID | None) -> ResearchRun:
        if data.idempotency_key:
            existing = await self.repo.get_by_idempotency_key(tenant_id, data.idempotency_key)
            if existing:
                return existing

        run = await self.repo.create_run(
            tenant_id=tenant_id,
            data=data.model_dump(),
            created_by_user_id=created_by_user_id,
        )
        return run

    async def get_run_with_counts(self, tenant_id: UUID, run_id: UUID) -> ResearchRunWithCounts | None:
        run = await self.repo.get_by_id(tenant_id, run_id)
        if not run:
            return None
        counts = await self.repo.count_steps_by_status(tenant_id, run_id)
        return ResearchRunWithCounts(**ResearchRunRead.model_validate(run).model_dump(), step_counts=counts)

    async def list_steps(self, tenant_id: UUID, run_id: UUID):
        return await self.repo.list_steps(tenant_id, run_id)

    async def validate_bundle(self, bundle: RunBundleV1) -> BundleValidationResponse:
        errors: List[BundleValidationError] = []
        sha256s = [src.sha256 for src in bundle.sources]
        if len(sha256s) != len(set(sha256s)):
            errors.append(BundleValidationError(loc="sources.sha256", msg="SHA256 values must be unique"))
            
        # Source integrity checks
        for i, src in enumerate(bundle.sources):
            # Reject sources with empty content_text
            if not src.content_text or not src.content_text.strip():
                errors.append(BundleValidationError(
                    loc=f"sources[{i}].content_text",
                    msg="Source content_text must be non-empty"
                ))
                continue
                
            # Verify SHA256 matches content_text
            computed_sha256 = _sha256(src.content_text)
            if computed_sha256 != src.sha256.lower():
                errors.append(BundleValidationError(
                    loc=f"sources[{i}].sha256",
                    msg=f"SHA256 mismatch: expected {computed_sha256}, got {src.sha256}"
                ))
        
        return BundleValidationResponse.from_errors(errors)

    async def accept_bundle(
        self,
        tenant_id: UUID,
        run_id: UUID,
        bundle: RunBundleV1,
    ) -> Tuple[BundleAcceptedResponse, bool]:
        run = await self.repo.get_by_id(tenant_id, run_id)
        if not run:
            raise ValueError("run_not_found")

        if bundle.run_id != run_id:
            raise ValueError("bundle_run_id_mismatch")

        # Validate bundle integrity first
        validation_result = await self.validate_bundle(bundle)
        if not validation_result.ok:
            error_msg = "; ".join([f"{e.loc}: {e.msg}" for e in validation_result.errors])
            raise ValueError(f"bundle_validation_failed: {error_msg}")

        canonical = _canonical_json(bundle.model_dump())
        bundle_hash = _sha256(canonical)

        if run.bundle_sha256 and run.bundle_sha256 == bundle_hash:
            return (
                BundleAcceptedResponse(
                    run_id=run.id,
                    bundle_sha256=bundle_hash,
                    status=run.status,
                    already_accepted=True,
                    message="Bundle already accepted",
                ),
                False,
            )

        # Company research run ID is optional - if not set, Phase 2 ingestion is skipped
        if not run.company_research_run_id:
            # Just store the bundle without calling Phase 2 ingestion
            pass

        # Validate proposal JSON with Phase 2 schema
        try:
            proposal = AIProposal(**bundle.proposal_json)
        except ValidationError as exc:
            errors = [BundleValidationError(loc="proposal_json", msg=str(exc))]
            raise ValueError(json.dumps([e.model_dump() for e in errors]))

        # Map sha256 -> source
        sha256_to_source = {src.sha256: src for src in bundle.sources}
        
        # Build temp_id -> sha256 mapping for backward compatibility
        temp_id_to_sha256 = {}
        for src in bundle.sources:
            if src.temp_id:
                temp_id_to_sha256[src.temp_id] = src.sha256

        # Evidence rule: each company must have evidence_snippets and source_sha256s
        valid_sha256s = set(sha256_to_source.keys())
        for company in proposal.companies:
            # Check if company has evidence_snippets and source_sha256s
            if hasattr(company, 'evidence_snippets') and hasattr(company, 'source_sha256s'):
                if not company.evidence_snippets:
                    raise ValueError(f"company_missing_evidence_snippets:{company.name}")
                if not company.source_sha256s:
                    raise ValueError(f"company_missing_source_sha256s:{company.name}")
                # Validate source_sha256s exist in bundle
                for sha256 in company.source_sha256s:
                    if sha256 not in valid_sha256s:
                        raise ValueError(f"company_references_unknown_source:{company.name}:{sha256}")
            else:
                # Backward compatibility: check for metric-level evidence with temp_id translation
                has_evidence = False
                for metric in company.metrics:
                    if metric.source_temp_id and metric.evidence_snippet:
                        # Translate temp_id to sha256 if available
                        if metric.source_temp_id in temp_id_to_sha256:
                            has_evidence = True
                            break
                        elif metric.source_temp_id in valid_sha256s:  # direct sha256 reference
                            has_evidence = True
                            break
                if not has_evidence:
                    raise ValueError(f"company_missing_evidence:{company.name}")

        # Upsert sources by sha256
        sha256_to_source_id: Dict[str, UUID] = {}
        for src in bundle.sources:
            source_id = await self._get_or_create_source(
                tenant_id=tenant_id,
                company_research_run_id=run.company_research_run_id,
                source=src,
            )
            sha256_to_source_id[src.sha256] = source_id
            
        # Build legacy temp_id mapping for Phase 2 compatibility
        temp_id_to_source_id = {}
        for src in bundle.sources:
            if src.temp_id:
                temp_id_to_source_id[src.temp_id] = sha256_to_source_id[src.sha256]

        # Upsert steps
        await self.repo.upsert_steps(
            tenant_id=tenant_id,
            run_id=run_id,
            steps=[
                {
                    "step_key": step.step_key,
                    "step_type": step.step_type,
                    "status": step.status,
                    "inputs_json": step.inputs_json,
                    "outputs_json": step.outputs_json,
                    "provider_meta": step.provider_meta,
                    "started_at": step.started_at,
                    "finished_at": step.finished_at,
                    "output_sha256": step.output_sha256,
                    "error": step.error,
                }
                for step in bundle.steps
            ],
        )

        # Update run record
        run.plan_json = bundle.plan_json
        run.bundle_sha256 = bundle_hash
        run.status = "submitted"

        # Call Phase 2 ingestion only if company_research_run_id is set
        if run.company_research_run_id:
            proposal_service = AIProposalService(self.db)
            ingestion_result = await proposal_service.ingest_proposal(
                tenant_id=tenant_id,
                run_id=run.company_research_run_id,
                proposal=proposal,
                source_id_map_override=temp_id_to_source_id,
            )

            if not ingestion_result.success:
                run.status = "failed"
                await self.db.commit()
                raise ValueError("ingestion_failed:" + ";".join(ingestion_result.errors))

        await self.db.commit()
        return (
            BundleAcceptedResponse(
                run_id=run.id,
                bundle_sha256=bundle_hash,
                status=run.status,
                already_accepted=False,
                message="Bundle accepted and ingested",
            ),
            True,
        )

    async def _get_or_create_source(
        self,
        tenant_id: UUID,
        company_research_run_id: UUID,
        source,
    ) -> UUID:
        """Upsert source_documents by (tenant_id, content_hash)."""
        existing = await self.db.execute(
            select(ResearchSourceDocument).where(
                ResearchSourceDocument.tenant_id == tenant_id,
                ResearchSourceDocument.content_hash == source.sha256,
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            return found.id

        doc = ResearchSourceDocument(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            company_research_run_id=company_research_run_id,
            source_type="ai_proposal",
            title=source.title,
            url=source.url,
            provider=source.meta.get("provider"),
            mime_type=source.mime_type,
            content_text=source.content_text,
            content_hash=source.sha256,
            status="processed",
            fetched_at=source.retrieved_at,
            meta=source.meta,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc.id

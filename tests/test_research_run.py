import asyncio
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.company_research import CompanyResearchRun
from app.models.tenant import Tenant
from app.services.research_run_service import ResearchRunService
from app.schemas.research_run import ResearchRunCreate, RunBundleV1, RunStepV1, SourceV1
from app.schemas.ai_proposal import AIProposal


@pytest.mark.db
@pytest.mark.asyncio
async def test_create_run_idempotent():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            pytest.skip("No tenant available")
        tenant_uuid = tenant.id
        
        service = ResearchRunService(db)
        target_run = await _get_company_run(db, tenant_uuid)
        if not target_run:
            pytest.skip("No company_research_run available")
        data = ResearchRunCreate(
            objective="Test run",
            constraints={},
            rank_spec={},
            idempotency_key="idempo-1",
            company_research_run_id=target_run.id,
        )
        first = await service.create_run(tenant_uuid, data, None)
        second = await service.create_run(tenant_uuid, data, None)
        await db.commit()
        assert first.id == second.id


@pytest.mark.db
@pytest.mark.asyncio
async def test_bundle_upload_idempotent_and_steps_dedup():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            pytest.skip("No tenant available")
        tenant_uuid = tenant.id
        
        service = ResearchRunService(db)
        target_run = await _get_company_run(db, tenant_uuid)
        if not target_run:
            pytest.skip("No company_research_run available")

        run = await service.create_run(
            tenant_uuid,
            ResearchRunCreate(
                objective="Bundle ingest",
                constraints={},
                rank_spec={},
                idempotency_key=str(uuid.uuid4()),
                company_research_run_id=target_run.id,
            ),
            None,
        )
        await db.commit()

        bundle = _make_bundle(run.id)

        resp, ingested = await service.accept_bundle(tenant_uuid, run.id, bundle)
        assert ingested is True
        assert resp.bundle_sha256

        resp2, ingested2 = await service.accept_bundle(tenant_uuid, run.id, bundle)
        assert ingested2 is False
        assert resp2.already_accepted is True

        steps = await service.list_steps(tenant_uuid, run.id)
        assert len(steps) == 1


@pytest.mark.db
@pytest.mark.asyncio
async def test_bundle_validation_missing_source_meta_temp_id():
    """Test that bundles work without temp_id when using sha256 references."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            pytest.skip("No tenant available")
        tenant_uuid = tenant.id
        
        service = ResearchRunService(db)
        target_run = await _get_company_run(db, tenant_uuid)
        if not target_run:
            pytest.skip("No company_research_run available")

        run = await service.create_run(
            tenant_uuid,
            ResearchRunCreate(
                objective="SHA256-only bundle",
                constraints={},
                rank_spec={},
                company_research_run_id=target_run.id,
            ),
            None,
        )
        await db.commit()

        # Bundle without temp_id should work with sha256-based evidence
        sha256_bundle = _make_bundle_with_sha256_evidence(run.id)
        resp, ingested = await service.accept_bundle(tenant_uuid, run.id, sha256_bundle)
        assert ingested is True
        assert resp.bundle_sha256


async def _get_company_run(db, tenant_id):
    result = await db.execute(
        select(CompanyResearchRun).where(CompanyResearchRun.tenant_id == tenant_id).limit(1)
    )
    return result.scalar_one_or_none()


def _make_bundle(run_id: uuid.UUID, include_temp_id: bool = True) -> RunBundleV1:
    temp_id = "source_1" if include_temp_id else None
    source = SourceV1(
        sha256="4d186321c1a7f0f354b297e8914ab2400000000000000000000000000000000",
        url="https://example.com",
        retrieved_at=datetime.utcnow(),
        mime_type="text/html",
        title="Example",
        content_text="Example content",
        meta={"provider": "tester"},
        temp_id=temp_id,
    )

    proposal = AIProposal(
        query="q",
        sources=[
            {
                "temp_id": "source_1",
                "title": "Example",
                "url": "https://example.com",
                "provider": "tester",
                "fetched_at": datetime.utcnow(),
            }
        ],
        companies=[
            {
                "name": "Demo Co",
                "metrics": [
                    {
                        "key": "fleet_size",
                        "type": "number",
                        "value": 1,
                        "source_temp_id": "source_1",
                        "evidence_snippet": "evidence",
                    }
                ],
            }
        ],
    )

    return RunBundleV1(
        version="run_bundle_v1",
        run_id=run_id,
        plan_json={"steps": 1},
        steps=[
            RunStepV1(
                step_key="s1",
                step_type="validate",
                status="ok",
                inputs_json={},
                outputs_json={},
                provider_meta={},
            )
        ],
        sources=[source],
        proposal_json=json.loads(proposal.model_dump_json()),
    )


def _make_bundle_with_sha256_evidence(run_id: uuid.UUID) -> RunBundleV1:
    sha256_val = "5e884321c1a7f0f354b297e8914ab2411111111111111111111111111111111"
    source = SourceV1(
        sha256=sha256_val,
        url="https://example.com/sha256",
        retrieved_at=datetime.utcnow(),
        mime_type="text/html", 
        title="Example SHA256",
        content_text="Example content with SHA256",
        meta={"provider": "tester"},
        # No temp_id
    )

    # Create proposal with company-level evidence
    proposal_dict = {
        "query": "q",
        "sources": [
            {
                "temp_id": "unused",  # This won't be used
                "title": "Example SHA256",
                "url": "https://example.com/sha256",
                "provider": "tester",
                "fetched_at": datetime.utcnow().isoformat(),
            }
        ],
        "companies": [
            {
                "name": "Demo Co SHA256",
                "metrics": [
                    {
                        "key": "fleet_size",
                        "type": "number",
                        "value": 1,
                    }
                ],
                "evidence_snippets": ["Company evidence snippet"],
                "source_sha256s": [sha256_val],
            }
        ],
    }

    return RunBundleV1(
        version="run_bundle_v1",
        run_id=run_id,
        plan_json={"steps": 1},
        steps=[
            RunStepV1(
                step_key="s1",
                step_type="validate",
                status="ok",
            )
        ],
        sources=[source],
        proposal_json=proposal_dict,
    )

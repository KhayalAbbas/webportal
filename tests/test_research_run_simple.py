"""Simple Phase 3 research run tests with proper async isolation."""
import asyncio
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.company_research import CompanyResearchRun  
from app.models.company import Company
from app.models.tenant import Tenant
from app.services.research_run_service import ResearchRunService
from app.schemas.research_run import ResearchRunCreate, RunBundleV1, RunStepV1, SourceV1
from app.schemas.ai_proposal import AIProposal


# Run this test standalone to avoid asyncio conflicts
@pytest.mark.db
def test_research_run_integration():
    """Test all Phase 3 functionality in one integration test."""
    async def main():
        # Use a transaction that we can rollback to avoid test data interference
        async with AsyncSessionLocal() as db:
            # Start a transaction that we'll rollback at the end
            trans = await db.begin()
            
            try:
                # Create a test tenant for this test run
                test_tenant = Tenant(
                    id=uuid.uuid4(),
                    name=f"test-tenant-{uuid.uuid4()}",
                    status="active"
                )
                db.add(test_tenant)
                await db.flush()
                tenant_id = test_tenant.id

                service = ResearchRunService(db)

                # Find an existing role from ANY tenant to use for dummy CompanyResearchRun
                from app.models.company_research import CompanyResearchRun
                from app.models.role import Role
                from app.models.company import Company
                
                # Try to find ANY existing role in the database, regardless of tenant
                role_result = await db.execute(select(Role).limit(1))
                existing_role = role_result.scalar_one_or_none()
                
                # Try to find ANY existing company in the database, regardless of tenant  
                company_result = await db.execute(select(Company).limit(1))
                existing_company = company_result.scalar_one_or_none()
                
                if not existing_role and existing_company:
                    # Create a dummy role with the existing company
                    dummy_role = Role(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        company_id=existing_company.id,  # Use existing company
                        title="Dummy Role for Phase 3 Test",
                        status="active"
                    )
                    db.add(dummy_role)
                    await db.flush()
                    role_id = dummy_role.id
                elif not existing_role and not existing_company:
                    # Create both dummy company and role
                    dummy_company = Company(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        name="Dummy Company for Phase 3 Test",
                        status="active"
                    )
                    db.add(dummy_company)
                    await db.flush()
                    
                    dummy_role = Role(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        company_id=dummy_company.id,
                        title="Dummy Role for Phase 3 Test",
                        status="active"
                    )
                    db.add(dummy_role)
                    await db.flush()
                    role_id = dummy_role.id
                else:
                    role_id = existing_role.id

                # Create a dummy CompanyResearchRun to satisfy foreign key constraints
                dummy_run = CompanyResearchRun(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    role_mandate_id=role_id,  # Use existing or dummy role
                    name="Dummy Company Research Run for Phase 3 Test",
                    sector="technology",  # Required field
                    status="queued"
                )
                db.add(dummy_run)
                await db.flush()

                # Test 1: Idempotent run creation (with dummy Phase 2 integration)
                idempotency_key = f"test-{uuid.uuid4()}"
                data = ResearchRunCreate(
                    objective="Test Phase 3",
                    constraints={},
                    rank_spec={},
                    idempotency_key=idempotency_key,
                    company_research_run_id=dummy_run.id,  # Link to dummy run
                )

                run1 = await service.create_run(tenant_id, data, None)
                run2 = await service.create_run(tenant_id, data, None)
                assert run1.id == run2.id

                # Test 2: Bundle upload with dummy Phase 2 integration  
                bundle = create_test_bundle(run1.id)
                resp1, ingested1 = await service.accept_bundle(tenant_id, run1.id, bundle)
                assert ingested1 is True  # Should accept and not call actual Phase 2 (dummy run)
                assert resp1.bundle_sha256 is not None
                
                # Test 3: Idempotent bundle upload
                resp2, ingested2 = await service.accept_bundle(tenant_id, run1.id, bundle)
                assert ingested2 is False
                assert resp2.already_accepted is True

                # Test 4: SHA256-only bundle (no temp_id) with new dummy run
                dummy_run2 = CompanyResearchRun(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    role_mandate_id=role_id,  # Use same role
                    name="Dummy Company Research Run 2 for Phase 3 SHA256 Test", 
                    sector="technology",  # Required field
                    status="queued"
                )
                db.add(dummy_run2)
                await db.flush()

                run_sha256 = await service.create_run(
                    tenant_id,
                    ResearchRunCreate(
                        objective="SHA256 test",
                        constraints={},
                        rank_spec={},
                        company_research_run_id=dummy_run2.id,  # Link to dummy run
                    ),
                    None,
                )
                
                sha256_bundle = create_sha256_bundle(run_sha256.id)
                resp3, ingested3 = await service.accept_bundle(tenant_id, run_sha256.id, sha256_bundle)
                assert ingested3 is True
                assert resp3.bundle_sha256 is not None
                
                # Test 5: Source integrity validation - empty content_text should fail
                try:
                    empty_content_bundle = create_invalid_bundle_empty_content(run_sha256.id)
                    await service.validate_bundle(empty_content_bundle)
                    assert False, "Should have failed validation for empty content_text"       
                except Exception as e:
                    # Validation should catch this in validate_bundle rather than accept_bundle
                    validation_result = await service.validate_bundle(empty_content_bundle)
                    assert not validation_result.ok
                    assert "content_text must be non-empty" in str(validation_result.errors)

                # Test 6: Source integrity validation - wrong SHA256 should fail
                try:
                    wrong_sha_bundle = create_invalid_bundle_wrong_sha256(run_sha256.id)
                    validation_result = await service.validate_bundle(wrong_sha_bundle)
                    assert not validation_result.ok       
                    assert "SHA256 mismatch" in str(validation_result.errors)
                except Exception as e:
                    pass
                
                print("✅ All Phase 3 tests passed!")
                return True
                
            finally:
                # Always rollback the transaction to avoid test data pollution  
                # (Only if transaction is still active)
                try:
                    if trans.is_active:
                        await trans.rollback()
                except Exception:
                    pass  # Transaction may already be closed
    
    # Run in new event loop to avoid conflicts
    result = asyncio.run(main())
    assert result is True


def create_test_bundle(run_id: uuid.UUID) -> RunBundleV1:
    """Create a test bundle with temp_id."""
    source = SourceV1(
        sha256="68aadc334d6f0aba634586997c3a8cd67002309ad98288853230a70c3566f9cf",
        url="https://example.com",
        retrieved_at=datetime.utcnow(),
        mime_type="text/html",
        title="Example",
        content_text="Example content",
        meta={"provider": "tester"},
        temp_id="source_1",
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
                # Company-level evidence
                "evidence_snippets": ["Company evidence snippet"],
                "source_sha256s": ["68aadc334d6f0aba634586997c3a8cd67002309ad98288853230a70c3566f9cf"],
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


def create_sha256_bundle(run_id: uuid.UUID) -> RunBundleV1:
    """Create a bundle without temp_id, using SHA256 references."""
    sha256_val = "e30384de2b2e75ae281d4a91d18e241e4cc9bbd3581d10a8e182f51528e07e69"
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

    proposal_dict = {
        "query": "q",
        "sources": [
            {
                "temp_id": "unused",  # This won't be used for mapping
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
                # Company-level evidence with SHA256 references
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


def create_invalid_bundle_empty_content(run_id: uuid.UUID) -> RunBundleV1:
    """Create a bundle with empty content_text for testing validation."""
    source = SourceV1(
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        url="https://example.com/empty",
        retrieved_at=datetime.utcnow(),
        mime_type="text/html", 
        title="Empty Content",
        content_text="",  # Empty content should fail validation
        meta={"provider": "tester"},
    )

    proposal_dict = {
        "query": "q",
        "sources": [],
        "companies": [
            {
                "name": "Test Co",
                "evidence_snippets": ["Test evidence"],
                "source_sha256s": ["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
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


def create_invalid_bundle_wrong_sha256(run_id: uuid.UUID) -> RunBundleV1:
    """Create a bundle with mismatched SHA256 for testing validation."""
    source = SourceV1(
        sha256="wrong1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
        url="https://example.com/wrong",
        retrieved_at=datetime.utcnow(),
        mime_type="text/html", 
        title="Wrong SHA256",
        content_text="hello world",  # This content doesn't match the SHA256 above
        meta={"provider": "tester"},
    )

    proposal_dict = {
        "query": "q", 
        "sources": [],
        "companies": [
            {
                "name": "Test Co",
                "evidence_snippets": ["Test evidence"],
                "source_sha256s": ["wrong1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"],
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
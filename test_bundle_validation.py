"""
Create a working bundle upload test using existing schemas
"""
import asyncio
import json
from uuid import uuid4
from datetime import datetime
from app.schemas.research_run import (
    RunBundleV1, 
    RunStepV1, 
    SourceV1
)

async def test_bundle_upload_validation():
    """
    Test bundle creation and upload validation with correct schema
    """
    print("Creating RunBundleV1...")
    
    # Create a minimal working bundle
    test_bundle = RunBundleV1(
        version="run_bundle_v1",
        run_id=uuid4(),
        plan_json={"objective": "Find technology companies"},
        steps=[],
        sources=[
            SourceV1(
                sha256="a" * 64,  # Valid SHA256 format
                url="https://test.com",
                content_text="Test Company is a technology company"
            )
        ],
        proposal_json={
            "query": "technology companies",
            "companies": [
                {
                    "name": "Test Company",
                    "industry": "Technology", 
                    "employees": 100,
                    "revenue": 10000000,
                    "description": "A test technology company",
                    "website": "https://test.com",
                    "headquarters": "San Francisco, CA",
                    "evidence_snippets": [
                        "Test Company is a technology company"
                    ],
                    "source_sha256s": ["a" * 64]
                }
            ],
            "version_info": {
                "created_at": str(datetime.now()),
                "creator": "test_system"
            }
        }
    )
    
    print(f"✅ Bundle created successfully:")
    print(f"  Version: {test_bundle.version}")
    print(f"  Run ID: {test_bundle.run_id}")
    print(f"  Steps: {len(test_bundle.steps)}")
    print(f"  Sources: {len(test_bundle.sources)}")
    print(f"  Proposal companies: {len(test_bundle.proposal_json.get('companies', []))}")
    
    # Test bundle->proposal transformation
    from app.services.research_run_service import transform_bundle_to_proposal
    
    try:
        proposal = transform_bundle_to_proposal(test_bundle)
        print(f"\n✅ Bundle->Proposal transformation successful")
        print(f"  AIProposal companies: {len(proposal.companies)}")
        print(f"  AIProposal sources: {len(proposal.sources)}")
        return True
    except Exception as e:
        print(f"\n❌ Bundle->Proposal transformation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_bundle_upload_validation())
    print(f"\nTest result: {'PASS' if success else 'FAIL'}")
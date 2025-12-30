"""
Test bundle upload validation with invalid bundle for error handling
"""
import asyncio
from uuid import uuid4
from datetime import datetime
from app.schemas.research_run import RunBundleV1, SourceV1
from app.services.research_run_service import transform_bundle_to_proposal

async def test_invalid_bundle_validation():
    """
    Test upload validation with invalid bundle to prove error handling
    """
    print("Testing invalid bundle (missing evidence_snippets)...")
    
    # Create bundle with missing required evidence_snippets
    invalid_bundle = RunBundleV1(
        version="run_bundle_v1",
        run_id=uuid4(),
        plan_json={"objective": "Find technology companies"},
        steps=[],
        sources=[
            SourceV1(
                sha256="b" * 64,
                url="https://invalid.com",
                content_text="Invalid company data"
            )
        ],
        proposal_json={
            "query": "technology companies",
            "companies": [
                {
                    "name": "Invalid Company",
                    "industry": "Technology", 
                    "employees": 100,
                    "revenue": 10000000,
                    # Missing evidence_snippets - should fail validation
                    "source_sha256s": ["b" * 64]
                }
            ],
            "version_info": {
                "created_at": str(datetime.now()),
                "creator": "test_system"
            }
        }
    )
    
    print("Testing bundle->proposal transformation (should fail)...")
    
    try:
        proposal = transform_bundle_to_proposal(invalid_bundle)
        print("❌ ERROR: Invalid bundle should have failed validation!")
        return False
    except ValueError as e:
        print(f"✅ Bundle validation correctly failed: {e}")
        return True
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_invalid_bundle_validation())
    print(f"\nInvalid bundle test result: {'PASS' if success else 'FAIL'}")
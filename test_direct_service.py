"""
Direct test of research_run_service.py accept_bundle functionality
"""
import asyncio
import json
from uuid import uuid4, UUID
from app.services.research_run_service import ResearchRunService, transform_bundle_to_proposal
from app.schemas.research_run import RunBundleV1, RunBundleCompany
from app.core.database import async_session

async def test_direct_bundle_processing():
    """
    Test bundle processing directly through service layer
    """
    # Create a test bundle
    test_bundle = RunBundleV1(
        run_id=uuid4(),
        version="1.0", 
        companies=[
            RunBundleCompany(
                name="Test Company",
                industry="Technology",
                employee_count=100,
                revenue=10000000,
                headquarters="San Francisco, CA",
                website="https://test.com",
                description="A test company",
                sources=[]
            )
        ],
        version_info={
            "created_at": "2024-12-19T10:00:00Z",
            "creator": "test_system"
        }
    )
    
    print("Test Bundle created:")
    print(f"  Run ID: {test_bundle.run_id}")
    print(f"  Companies: {len(test_bundle.companies)}")
    
    # Test transformation
    try:
        proposal = transform_bundle_to_proposal(test_bundle)
        print("\n✅ Bundle->Proposal transformation successful")
        print(f"  Companies in proposal: {len(proposal.companies)}")
        print(f"  Sources: {len(proposal.sources)}")
        return True
    except Exception as e:
        print(f"\n❌ Bundle->Proposal transformation failed: {e}")
        return False

    # Test validation
    async with async_session() as db:
        service = ResearchRunService(db)
        validation_result = await service.validate_bundle(test_bundle)
        
        if validation_result.ok:
            print("\n✅ Bundle validation passed")
        else:
            print(f"\n❌ Bundle validation failed:")
            for error in validation_result.errors:
                print(f"  {error.loc}: {error.msg}")

if __name__ == "__main__":
    success = asyncio.run(test_direct_bundle_processing())
    print(f"\nTest result: {'PASS' if success else 'FAIL'}")
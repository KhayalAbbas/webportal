"""
Quick test to debug run creation.
"""
import asyncio
from uuid import UUID
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.company_research_service import CompanyResearchService
from app.schemas.company_research import CompanyResearchRunCreate

pytestmark = [pytest.mark.asyncio, pytest.mark.db]

async def test_run_create():
    """Test creating a research run."""
    # Create async engine
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        service = CompanyResearchService(session)
        
        # Test data
        tenant_id = "b3909011-8bd3-439d-a421-3b70fae124e9"  # Test tenant
        role_mandate_id = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")  # Existing role
        user_id = UUID("8c8a5b84-f093-4279-a8a0-d5c9fb0dca7e")  # Test user
        
        run_create = CompanyResearchRunCreate(
            role_mandate_id=role_mandate_id,
            name="Test Run Debug",
            description="Testing run creation",
            sector="banking",
            region_scope=["US"],
            config={
                "ranking": {
                    "primary_metric": "total_assets",
                    "currency": "USD",
                    "as_of_year": 2024,
                    "direction": "desc",
                    "fallback_years_back": 2
                },
                "enrichment": {
                    "metrics_to_collect": ["total_assets"]
                }
            },
            status="active",
        )
        
        print(f"\n=== Creating run with tenant_id type: {type(tenant_id)}")
        print(f"tenant_id value: {tenant_id}")
        
        try:
            run = await service.create_research_run(
                tenant_id=tenant_id,
                data=run_create,
                created_by_user_id=user_id,
            )
            
            await session.commit()
            
            print(f"\n✅ Run created successfully!")
            print(f"Run ID: {run.id}")
            print(f"Run ID type: {type(run.id)}")
            print(f"Run name: {run.name}")
            print(f"Run tenant_id: {run.tenant_id}")
            print(f"Run tenant_id type: {type(run.tenant_id)}")
            
        except Exception as e:
            print(f"\n❌ Error creating run: {e}")
            print(f"Error type: {type(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_run_create())

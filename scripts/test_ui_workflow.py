"""
Simulate adding a text source and processing it.
This mimics what happens when a user pastes text in the UI.
"""
import asyncio
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import pytest

if os.environ.get('RUN_SERVER_TESTS') != '1':
    pytest.skip('Server not running; set RUN_SERVER_TESTS=1 to enable UI workflow HTTP tests', allow_module_level=True)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.company_research_service import CompanyResearchService
from app.services.company_extraction_service import CompanyExtractionService
from app.schemas.company_research import SourceDocumentCreate


async def test_add_and_process():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        service = CompanyResearchService(session)
        extraction_service = CompanyExtractionService(session)
        
        # Use an existing tenant and run
        tenant_id = "b3909011-8bd3-439d-a421-3b70fae124e9"
        
        # Use a known run ID from previous tests
        run_id = "f5f8686d-44f6-49a5-9d56-e83651c1507b"
        
        run = await service.get_research_run(tenant_id, run_id)
        if not run:
            print("Run not found")
            return
        
        print(f"Using run: {run_id}")
        print(f"Run name: {run.name}")
        print()
        
        # Test text to paste (mimics user input)
        test_text = """Bajaj Finance Limited
Shriram Finance Limited
Cholamandalam Investment & Finance Company Limited
Tata Capital Limited
PNB Housing Finance Limited"""
        
        print("Adding text source:")
        print("-" * 60)
        print(test_text)
        print("-" * 60)
        print()
        
        # Add source (mimics UI form submission)
        source = await service.add_source(
            tenant_id=tenant_id,
            data=SourceDocumentCreate(
                company_research_run_id=run_id,
                source_type="text",
                title="Test NBFC List",
                content_text=test_text,
            ),
        )
        
        print(f"✓ Source created: {source.id}")
        print(f"  Status: {source.status}")
        print(f"  Content length: {len(source.content_text or '')}")
        print()
        
        # Process sources (mimics clicking "Extract Companies" button)
        print("Processing sources...")
        result = await extraction_service.process_sources(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        
        print()
        print("✓ Processing complete!")
        print(f"  Processed: {result['processed']} sources")
        print(f"  Companies found: {result['companies_found']}")
        print(f"  New prospects: {result['companies_new']}")
        print(f"  Existing prospects: {result['companies_existing']}")
        print()
        
        # List prospects
        prospects = await service.list_prospects_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
            limit=20,
        )
        
        print(f"Total prospects in run: {len(prospects)}")
        print("\nLatest prospects:")
        for i, p in enumerate(prospects[-5:], 1):
            print(f"  {i}. {p.name_raw}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_add_and_process())

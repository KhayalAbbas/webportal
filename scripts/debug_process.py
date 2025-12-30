"""Debug process_sources to see what's happening."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument
from app.services.company_extraction_service import CompanyExtractionService


async def debug():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get one new source
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.source_type == 'text',
                ResearchSourceDocument.status == 'new'
            )
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("No failed sources")
            return
        
        print(f"Testing source: {source.id}")
        print(f"Content: {source.content_text[:200]}...")
        print(f"Status: {source.status}")
        
        service = CompanyExtractionService(session)
        
        # Test extraction directly
        print("\n1. Testing extraction...")
        companies = service._extract_company_names(source.content_text or "")
        print(f"   Found {len(companies)} companies")
        for name, snippet in companies[:3]:
            print(f"     - {name[:50]}")
        
        # Now try full process
        print("\n2. Testing process_sources...")
        try:
            result = await service.process_sources(
                tenant_id=source.tenant_id,
                run_id=source.company_research_run_id,
            )
            print(f"   Result: {result}")
        except Exception as e:
            print(f"   ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(debug())

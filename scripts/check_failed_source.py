"""Check the most recent failed source to debug."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument


async def check_failed():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get most recent source ordered by created_at
        result = await session.execute(
            select(ResearchSourceDocument)
            .order_by(ResearchSourceDocument.created_at.desc())
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("No sources found")
            return
        
        print(f"\n{'='*70}")
        print(f"Most Recent Source")
        print(f"{'='*70}")
        print(f"ID: {source.id}")
        print(f"Type: {source.source_type}")
        print(f"Status: {source.status}")
        print(f"Title: {source.title}")
        print(f"Created: {source.created_at}")
        print(f"\nContent Text:")
        print(f"  - Is None: {source.content_text is None}")
        print(f"  - Length: {len(source.content_text or '')}")
        print(f"  - Repr: {repr(source.content_text)[:200]}")
        
        if source.error_message:
            print(f"\nError Message:")
            print(f"  {source.error_message}")
        
        if source.content_text:
            print(f"\n{'='*70}")
            print("Actual Content:")
            print(f"{'='*70}")
            print(source.content_text[:500])
            print(f"{'='*70}")
            
            # Try extraction
            from app.services.company_extraction_service import CompanyExtractionService
            service = CompanyExtractionService(session)
            companies = service._extract_company_names(source.content_text)
            print(f"\nDirect extraction test: {len(companies)} companies")
            for name, snippet in companies[:5]:
                print(f"  - {name}")
        
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_failed())

"""Inspect actual source content from database."""
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


async def inspect():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.source_type == 'text')
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if source:
            print(f"Source ID: {source.id}")
            print(f"Status: {source.status}")
            print(f"Content length: {len(source.content_text or '')}")
            print(f"\nActual content:")
            print(repr(source.content_text))
            print(f"\n---\n")
            
            # Test extraction
            service = CompanyExtractionService(session)
            companies = service._extract_company_names(source.content_text or "")
            print(f"\nExtracted {len(companies)} companies:")
            for name, snippet in companies:
                print(f"  - {name}")
        else:
            print("No text sources found")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(inspect())

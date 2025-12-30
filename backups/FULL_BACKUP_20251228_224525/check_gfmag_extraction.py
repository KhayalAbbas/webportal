"""
Check what was extracted from the gfmag URL.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument, CompanyProspect

async def check_extraction():
    """Check what was extracted from gfmag."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Find the source document
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.url.like('%gfmag.com%'))
            .order_by(ResearchSourceDocument.created_at.desc())
        )
        sources = result.scalars().all()
        
        if not sources:
            print("❌ No gfmag sources found")
            return
        
        for source in sources:
            print(f"\n{'='*80}")
            print(f"Source ID: {source.id}")
            print(f"URL: {source.url}")
            print(f"Title: {source.title}")
            print(f"Status: {source.status}")
            print(f"Run ID: {source.company_research_run_id}")
            print(f"Created: {source.created_at}")
            
            # Get the extracted companies for this run
            result = await session.execute(
                select(CompanyProspect)
                .where(CompanyProspect.company_research_run_id == source.company_research_run_id)
            )
            prospects = result.scalars().all()
            
            print(f"\n--- Extracted {len(prospects)} prospects ---")
            for i, prospect in enumerate(prospects, 1):
                print(f"{i}. {prospect.name_raw}")
            
            # Show the raw content text (first 2000 chars)
            if source.content_text:
                print(f"\n--- Raw content (first 2000 chars) ---")
                print(source.content_text[:2000])
                print(f"... (total {len(source.content_text)} chars)")

if __name__ == "__main__":
    asyncio.run(check_extraction())

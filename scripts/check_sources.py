"""Check status of text sources."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument


async def check():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.source_type == 'text')
        )
        sources = result.scalars().all()
        
        print(f'\nTotal text sources: {len(sources)}\n')
        
        status_counts = {}
        for s in sources:
            status_counts[s.status] = status_counts.get(s.status, 0) + 1
            print(f'  {s.id}')
            print(f'    Status: {s.status}')
            print(f'    Title: {s.title}')
            print(f'    Run: {s.company_research_run_id}')
            if s.error_message:
                print(f'    Error: {s.error_message[:100]}')
            print()
        
        print(f'Status summary:')
        for status, count in status_counts.items():
            print(f'  {status}: {count}')
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

"""Reset processed sources to new."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument


async def reset():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(
            update(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.source_type == 'text',
                ResearchSourceDocument.status.in_(['processed', 'failed'])
            )
            .values(status='new', error_message=None)
        )
        await session.commit()
        print(f'Reset {result.rowcount} sources to new status')
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reset())

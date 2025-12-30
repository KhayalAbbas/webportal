"""Check the error message from the Wikipedia source."""
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.company_research import ResearchSourceDocument

async def check_error():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.url.like('%wikipedia%'))
            .order_by(ResearchSourceDocument.updated_at.desc())
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if source:
            print(f"URL: {source.url}")
            print(f"Status: {source.status}")
            print(f"Error: {source.error_message}")
            print(f"Content length: {len(source.content_text or '')}")

if __name__ == "__main__":
    asyncio.run(check_error())

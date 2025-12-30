"""Reprocess the specific failed source."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument
from app.services.company_extraction_service import CompanyExtractionService


async def reprocess():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get the most recent failed source
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.status == 'failed')
            .order_by(ResearchSourceDocument.created_at.desc())
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("No failed sources found")
            return
        
        print(f"\nReprocessing source: {source.id}")
        print(f"Title: {source.title}")
        print(f"Content length: {len(source.content_text or '')}")
        print(f"Previous error: {source.error_message}")
        print()
        
        # Reset to new status
        await session.execute(
            update(ResearchSourceDocument)
            .where(ResearchSourceDocument.id == source.id)
            .values(status='new', error_message=None)
        )
        await session.commit()
        
        print("Reset to 'new' status")
        print("Processing...")
        print()
        
        # Process
        service = CompanyExtractionService(session)
        result = await service.process_sources(
            tenant_id=source.tenant_id,
            run_id=source.company_research_run_id,
        )
        
        print("✅ Results:")
        print(f"  Processed: {result['processed']} sources")
        print(f"  Companies found: {result['companies_found']}")
        print(f"  New prospects: {result['companies_new']}")
        print(f"  Existing prospects: {result['companies_existing']}")
        print()
        
        # Check final status
        await session.refresh(source)
        print(f"Final status: {source.status}")
        if source.error_message:
            print(f"Error: {source.error_message}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reprocess())

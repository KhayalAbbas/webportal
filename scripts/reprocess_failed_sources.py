"""
Script to reprocess failed text sources after extraction logic fix.

Resets failed text sources to 'new' status so they can be reprocessed
without creating duplicate prospects.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import ResearchSourceDocument
from app.services.company_extraction_service import CompanyExtractionService


async def reprocess_failed_sources():
    """Reprocess all failed text sources."""
    
    # Create async engine
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
    )
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        # Find all failed text sources
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.source_type == "text",
                ResearchSourceDocument.status == "failed"
            )
        )
        failed_sources = result.scalars().all()
        
        print(f"\nFound {len(failed_sources)} failed text sources")
        
        if not failed_sources:
            print("No failed sources to reprocess")
            return
        
        # Reset status to 'new' so they'll be picked up by process_sources
        for source in failed_sources:
            print(f"  - Resetting source {source.id}: {source.title or 'Untitled'}")
            source.status = "new"
            source.error_message = None
        
        await session.commit()
        
        print(f"\nReset {len(failed_sources)} sources to 'new' status")
        print("\nTo process them, run process_sources() for each research run:")
        
        # Group by run_id
        runs = {}
        for source in failed_sources:
            run_id = source.company_research_run_id
            if run_id not in runs:
                runs[run_id] = []
            runs[run_id].append(source)
        
        print(f"\nAffected research runs ({len(runs)} total):")
        for run_id, sources in runs.items():
            print(f"  - Run {run_id}: {len(sources)} sources")
            
            # Get run details
            from app.models.company_research import CompanyResearchRun
            result = await session.execute(
                select(CompanyResearchRun)
                .where(CompanyResearchRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                print(f"    Name: {run.name}")
                print(f"    Sector: {run.sector}")
                print(f"    URL: http://127.0.0.1:8000/ui/company-research/runs/{run_id}")
        
        print("\nProcessing sources now...")
        
        # Process each run
        for run_id, sources in runs.items():
            result = await session.execute(
                select(ResearchSourceDocument)
                .where(ResearchSourceDocument.company_research_run_id == run_id)
                .limit(1)
            )
            first_source = result.scalar_one_or_none()
            
            if first_source:
                tenant_id = first_source.tenant_id
                extraction_service = CompanyExtractionService(session)
                
                print(f"\nProcessing run {run_id}...")
                result = await extraction_service.process_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
                
                print(f"  ✓ Processed: {result['processed']} sources")
                print(f"  ✓ Companies found: {result['companies_found']}")
                print(f"  ✓ New prospects: {result['companies_new']}")
                print(f"  ✓ Existing prospects: {result['companies_existing']}")
        
        print("\n✅ Done! All failed sources have been reprocessed.")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reprocess_failed_sources())

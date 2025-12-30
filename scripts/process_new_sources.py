"""Process all new text sources."""
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


async def process_all():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all new text sources
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(
                ResearchSourceDocument.source_type == 'text',
                ResearchSourceDocument.status == 'new'
            )
        )
        sources = result.scalars().all()
        
        if not sources:
            print("No new sources to process")
            return
        
        # Group by run_id
        runs = {}
        for source in sources:
            run_id = source.company_research_run_id
            tenant_id = source.tenant_id
            if run_id not in runs:
                runs[run_id] = (tenant_id, [])
            runs[run_id][1].append(source)
        
        print(f"Found {len(sources)} new text sources across {len(runs)} runs\n")
        
        # Process each run
        for run_id, (tenant_id, run_sources) in runs.items():
            print(f"\n{'='*60}")
            print(f"Processing run: {run_id}")
            print(f"  Tenant: {tenant_id}")
            print(f"  Sources: {len(run_sources)}")
            
            # Show source content
            for source in run_sources:
                print(f"\n  Source: {source.title}")
                content = source.content_text or ""
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                print(f"    Lines: {len(lines)}")
                for line in lines[:5]:
                    print(f"      - {line[:80]}")
                if len(lines) > 5:
                    print(f"      ... and {len(lines) - 5} more lines")
            
            extraction_service = CompanyExtractionService(session)
            
            try:
                result = await extraction_service.process_sources(
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
                
                print(f"\n  ✅ Results:")
                print(f"    Processed: {result['processed']} sources")
                print(f"    Companies found: {result['companies_found']}")
                print(f"    New prospects: {result['companies_new']}")
                print(f"    Existing prospects: {result['companies_existing']}")
                
            except Exception as e:
                print(f"\n  ❌ Error: {str(e)}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'='*60}")
        print("✅ Done!")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(process_all())

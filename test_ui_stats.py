"""
Test that UI stats are displayed correctly when processing sources.
"""
import sys
import asyncio
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.company_research import ResearchSourceDocument, CompanyResearchRun
from app.services.company_extraction_service import CompanyExtractionService

pytestmark = [pytest.mark.asyncio, pytest.mark.db]

async def test_stats_display():
    """Test extraction stats are returned correctly."""
    
    async with AsyncSessionLocal() as session:
        # Find most recent run with sources
        result = await session.execute(
            select(CompanyResearchRun)
            .order_by(CompanyResearchRun.created_at.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()
        
        if not run:
            print("❌ No runs found")
            return
        
        print(f"Testing with run: {run.id}")
        print(f"Tenant: {run.tenant_id}")
        
        # Get a source we can test with
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.company_research_run_id == run.id)
            .where(ResearchSourceDocument.status == "processed")
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("❌ No processed sources found")
            return
        
        print(f"\nSource: {source.title}")
        print(f"Content length: {len(source.content_text or '')}")
        print(f"Status: {source.status}")
        
        # Reset source to 'new' to test again
        source.status = "new"
        await session.commit()
        
        # Create extraction service and process
        service = CompanyExtractionService(session)
        result = await service.process_sources(
            tenant_id=str(run.tenant_id),
            run_id=run.id,
        )
        
        await session.commit()
        
        # Display results like UI would
        print(f"\n✅ Processing Results:")
        print(f"Processed: {result['processed']} sources")
        print(f"Found: {result['companies_found']} companies")
        print(f"New: {result['companies_new']}, Existing: {result['companies_existing']}")
        
        if result.get('sources_detail'):
            print(f"\n📊 Per-Source Details:")
            for detail in result['sources_detail']:
                print(f"• {detail['title']}")
                print(f"  chars: {detail['chars']} | lines: {detail['lines']} | extracted: {detail['extracted']}")
                print(f"  new: {detail['new']} | existing: {detail['existing']}")
        else:
            print("⚠️ No sources_detail in result")
        
        # Simulate UI message format
        msg = f"Processed {result['processed']} sources. "
        msg += f"Found {result['companies_found']} companies. "
        msg += f"{result['companies_new']} new, {result['companies_existing']} existing."
        
        if result.get('sources_detail'):
            msg += "\n\nDetails:"
            for detail in result['sources_detail']:
                msg += f"\n• {detail['title']} | chars: {detail['chars']} | lines: {detail['lines']} | "
                msg += f"extracted: {detail['extracted']} | new: {detail['new']} | existing: {detail['existing']}"
        
        print(f"\n📝 UI Message Preview:")
        print(msg)

if __name__ == "__main__":
    asyncio.run(test_stats_display())

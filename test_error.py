import asyncio
import sys
import pytest

# This legacy helper test targets old research models; skip in CI until updated.
pytest.skip('Legacy helper test; skip until migrated to current models', allow_module_level=True)

sys.path.insert(0, 'C:/ATS')

from app.services.company_extraction_service import CompanyExtractionService
from app.db.session import get_async_session_context
from sqlalchemy import select

async def test_process():
    """Test processing a source to see the actual error"""
    
    async with get_async_session_context() as session:
        # Get the source that's failing
        result = await session.execute(
            select(ResearchSourceDocument)
            .where(ResearchSourceDocument.run_id == 'f5f8686d-44f6-49a5-9d56-e83651c1507b')
            .order_by(ResearchSourceDocument.updated_at.desc())
            .limit(1)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            print("❌ Source not found")
            return
        
        print(f"Source ID: {source.id}")
        print(f"URL: {source.url}")
        print(f"Status: {source.status}")
        print(f"Type: {source.source_type}")
        print()
        
        try:
            service = CompanyExtractionService(session)
            
            # Test fetching
            print("Testing _fetch_content...")
            metadata = await service._fetch_content('test-tenant', source)
            print(f"✅ Fetch succeeded: {metadata}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_process())

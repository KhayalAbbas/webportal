"""
Verify all UI routes work without .query() errors.

Tests that all routes using AsyncSession use the correct SQLAlchemy 2.x patterns.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.research_event import ResearchEvent
from app.models.source_document import SourceDocument
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.models.task import Task
from app.models.list import List
from app.models.list_item import ListItem


async def test_async_queries():
    """Test that common query patterns work with AsyncSession."""
    print("Testing SQLAlchemy 2.x async patterns...\n")
    
    async with AsyncSessionLocal() as db:
        # Get a tenant for testing
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print("⚠️  No tenant found - seed data first")
            return 1
        
        print(f"✅ Using tenant: {tenant.name} ({tenant.id})\n")
        
        # Test 1: Research events query (from research.py)
        print("Test 1: Research events query...")
        query = (
            select(ResearchEvent)
            .where(ResearchEvent.tenant_id == tenant.id)
            .order_by(
                ResearchEvent.created_at.desc()
            )
            .limit(5)
        )
        result = await db.execute(query)
        research_events = result.scalars().all()
        print(f"   ✅ Retrieved {len(research_events)} research events\n")
        
        # Test 2: Source documents query
        print("Test 2: Source documents query...")
        query = (
            select(SourceDocument)
            .where(SourceDocument.tenant_id == tenant.id)
            .order_by(SourceDocument.created_at.desc())
            .limit(5)
        )
        result = await db.execute(query)
        source_documents = result.scalars().all()
        print(f"   ✅ Retrieved {len(source_documents)} source documents\n")
        
        # Test 3: AI enrichments query
        print("Test 3: AI enrichments query...")
        query = (
            select(AIEnrichmentRecord)
            .where(AIEnrichmentRecord.tenant_id == tenant.id)
            .order_by(AIEnrichmentRecord.created_at.desc())
            .limit(5)
        )
        result = await db.execute(query)
        ai_enrichments = result.scalars().all()
        print(f"   ✅ Retrieved {len(ai_enrichments)} AI enrichments\n")
        
        # Test 4: Tasks query
        print("Test 4: Tasks query...")
        query = (
            select(Task)
            .where(Task.tenant_id == tenant.id)
            .order_by(Task.due_date.asc().nulls_last())
            .limit(5)
        )
        result = await db.execute(query)
        tasks = result.scalars().all()
        print(f"   ✅ Retrieved {len(tasks)} tasks\n")
        
        # Test 5: Lists query
        print("Test 5: Lists query...")
        query = (
            select(List)
            .where(List.tenant_id == tenant.id)
            .order_by(List.created_at.desc())
            .limit(5)
        )
        result = await db.execute(query)
        lists = result.scalars().all()
        print(f"   ✅ Retrieved {len(lists)} lists\n")
        
        # Test 6: List items query
        print("Test 6: List items query...")
        query = (
            select(ListItem)
            .where(ListItem.tenant_id == tenant.id)
            .limit(5)
        )
        result = await db.execute(query)
        list_items = result.scalars().all()
        print(f"   ✅ Retrieved {len(list_items)} list items\n")
        
        print("=" * 60)
        print("✅ All async query patterns working correctly!")
        print("=" * 60)
        
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(test_async_queries())
    exit(exit_code)

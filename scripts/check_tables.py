"""Check if tables actually exist in the database."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def check_tables():
    async with AsyncSessionLocal() as db:
        # List all tables
        result = await db.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """))
        
        tables = [row[0] for row in result.fetchall()]
        
        print("=" * 60)
        print("ALL TABLES IN DATABASE")
        print("=" * 60)
        for table in tables:
            print(f"  ✓ {table}")
        print()
        
        # Check for company research tables specifically
        company_research_tables = [
            'company_research_runs',
            'company_prospects', 
            'company_prospect_evidence',
            'company_prospect_metrics'
        ]
        
        print("=" * 60)
        print("COMPANY RESEARCH TABLES CHECK")
        print("=" * 60)
        missing = []
        for table in company_research_tables:
            if table in tables:
                print(f"  ✓ {table} EXISTS")
            else:
                print(f"  ✗ {table} MISSING")
                missing.append(table)
        
        print()
        
        if missing:
            print(f"❌ Missing {len(missing)} tables: {', '.join(missing)}")
            print()
            print("The migration may not have run correctly.")
            print("Try running: alembic upgrade head")
        else:
            print("✅ All company research tables exist!")
            
            # Check if they're actually accessible
            try:
                result = await db.execute(text("SELECT COUNT(*) FROM company_research_runs"))
                count = result.scalar()
                print(f"✅ company_research_runs is accessible (contains {count} rows)")
            except Exception as e:
                print(f"❌ Error accessing company_research_runs: {e}")
        
        print()


if __name__ == "__main__":
    asyncio.run(check_tables())

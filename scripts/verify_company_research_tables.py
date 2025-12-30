"""
Quick verification script for company research tables.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def verify_tables():
    """Check that company research tables exist."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema='public' 
                AND table_name IN (
                    'company_research_run',
                    'company_prospect', 
                    'company_prospect_evidence',
                    'company_prospect_metric'
                )
                ORDER BY table_name
            """)
        )
        tables = [row[0] for row in result]
        
        print("✓ Company Research Tables Verification:")
        print("=" * 50)
        
        expected_tables = [
            'company_prospect',
            'company_prospect_evidence',
            'company_prospect_metric',
            'company_research_run'
        ]
        
        for table in expected_tables:
            if table in tables:
                print(f"  ✅ {table}")
            else:
                print(f"  ❌ {table} - MISSING!")
        
        print("=" * 50)
        print(f"✓ Total: {len(tables)}/{len(expected_tables)} tables created")
        
        if len(tables) == len(expected_tables):
            print("✓ All company research tables created successfully!")
            return True
        else:
            print("❌ Some tables are missing!")
            return False


if __name__ == "__main__":
    success = asyncio.run(verify_tables())
    exit(0 if success else 1)

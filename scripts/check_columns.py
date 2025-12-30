"""Verify company_prospects has all required columns."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def check_columns():
    async with AsyncSessionLocal() as db:
        # Get column information for company_prospects
        result = await db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'company_prospects'
            ORDER BY column_name
        """))
        
        columns = result.fetchall()
        
        print("=" * 70)
        print("company_prospects TABLE COLUMNS")
        print("=" * 70)
        for col in columns:
            nullable = "NULL" if col[2] == 'YES' else "NOT NULL"
            print(f"  {col[0]:30} {col[1]:20} {nullable}")
        
        print()


if __name__ == "__main__":
    asyncio.run(check_columns())

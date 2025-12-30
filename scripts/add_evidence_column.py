"""
Quick script to add missing column to company_prospect_evidence table.
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.db.session import engine

async def add_column():
    """Add search_query_used column if it doesn't exist."""
    
    async with engine.begin() as conn:
        # Check and add search_query_used
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'company_prospect_evidence' 
            AND column_name = 'search_query_used'
        """))
        
        if not result.fetchone():
            await conn.execute(text("""
                ALTER TABLE company_prospect_evidence 
                ADD COLUMN search_query_used TEXT
            """))
            print("✅ Added search_query_used column")
        else:
            print("✓ search_query_used column already exists")
        
        # Check and add raw_snippet
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'company_prospect_evidence' 
            AND column_name = 'raw_snippet'
        """))
        
        if not result.fetchone():
            await conn.execute(text("""
                ALTER TABLE company_prospect_evidence 
                ADD COLUMN raw_snippet TEXT
            """))
            print("✅ Added raw_snippet column")
        else:
            print("✓ raw_snippet column already exists")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_column())

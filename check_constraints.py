#!/usr/bin/env python3
"""Check applied constraints."""

import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/ats_db')
    
    # Check current constraints
    constraints = await conn.fetch("""
        SELECT constraint_name, constraint_type 
        FROM information_schema.table_constraints 
        WHERE table_name = 'company_prospect_evidence'
        ORDER BY constraint_name
    """)
    
    print('Current constraints:')
    for c in constraints:
        print(f'  {c["constraint_name"]}: {c["constraint_type"]}')
    
    # Check indexes
    indexes = await conn.fetch("""
        SELECT indexname, indexdef
        FROM pg_indexes 
        WHERE tablename = 'company_prospect_evidence'
        AND indexname LIKE '%dedup%'
        ORDER BY indexname
    """)
    
    print('\nUnique indexes for deduplication:')
    for idx in indexes:
        print(f'  {idx["indexname"]}')
    
    await conn.close()

asyncio.run(main())
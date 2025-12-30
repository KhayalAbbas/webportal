#!/usr/bin/env python3
"""Get best run ID."""

import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/ats_db')
    
    # Get the exact run ID with most linked evidence
    run = await conn.fetchrow("""
        SELECT 
            crr.id,
            cp.tenant_id,
            COUNT(cpe.id) as total_evidence,
            COUNT(CASE WHEN cpe.source_document_id IS NOT NULL THEN 1 END) as linked_evidence
        FROM company_research_runs crr
        JOIN company_prospects cp ON cp.company_research_run_id = crr.id
        JOIN company_prospect_evidence cpe ON cpe.company_prospect_id = cp.id
        WHERE cp.tenant_id = 'b3909011-8bd3-439d-a421-3b70fae124e9'
        GROUP BY crr.id, cp.tenant_id
        ORDER BY linked_evidence DESC, total_evidence DESC
        LIMIT 1
    """)
    
    print(f'Best run: {run["id"]}')
    print(f'Tenant: {run["tenant_id"]}')
    print(f'Total evidence: {run["total_evidence"]}')
    print(f'Linked evidence: {run["linked_evidence"]}')
    
    await conn.close()

asyncio.run(main())
#!/usr/bin/env python3
"""Check research runs."""

import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/ats_db')
    
    # Check all runs and their evidence counts
    runs = await conn.fetch("""
        SELECT 
            crr.id,
            cp.tenant_id,
            COUNT(cpe.id) as total_evidence,
            COUNT(CASE WHEN cpe.source_document_id IS NOT NULL THEN 1 END) as linked_evidence
        FROM company_research_runs crr
        JOIN company_prospects cp ON cp.company_research_run_id = crr.id
        JOIN company_prospect_evidence cpe ON cpe.company_prospect_id = cp.id
        GROUP BY crr.id, cp.tenant_id
        ORDER BY linked_evidence DESC, total_evidence DESC
    """)
    
    print('Research runs by evidence count:')
    for run in runs:
        print(f'  Run {str(run["id"])[:8]}..., Tenant {str(run["tenant_id"])[:8]}..., Total: {run["total_evidence"]}, Linked: {run["linked_evidence"]}')
    
    await conn.close()

asyncio.run(main())
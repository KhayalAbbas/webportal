#!/usr/bin/env python3
"""Check evidence linkage results after migration."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncio
import asyncpg

async def main():
    """Check the linkage results."""
    
    # Connect using the same async setup as the app
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ats_db"
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    print("=== PHASE 3.5 LINKAGE VERIFICATION ===")
    
    # Check source documents
    total_sd = await conn.fetchval("SELECT COUNT(*) FROM source_documents")
    print(f"Total source_documents: {total_sd}")
    
    if total_sd > 0:
        sd_sample = await conn.fetch("SELECT id, tenant_id, url FROM source_documents LIMIT 3")
        print(f"SD sample:")
        for row in sd_sample:
            print(f"  {row['id']}: tenant={row['tenant_id']}, url={row['url'][:50] if row['url'] else 'None'}...")
    
    # Check evidence with linkage
    total_evidence = await conn.fetchval("SELECT COUNT(*) FROM company_prospect_evidence")
    linked_evidence = await conn.fetchval("SELECT COUNT(*) FROM company_prospect_evidence WHERE source_document_id IS NOT NULL")
    print(f"Total evidence: {total_evidence}")
    print(f"Linked evidence: {linked_evidence}")
    
    if linked_evidence > 0:
        # Check actual linkage quality
        linkage_check = await conn.fetch("""
            SELECT 
                cpe.id,
                cpe.tenant_id AS cpe_tenant,
                cp.tenant_id AS cp_tenant,
                sd.tenant_id AS sd_tenant,
                cp.company_research_run_id AS cp_run,
                sd.company_research_run_id AS sd_run,
                cpe.source_url = sd.url AS url_match
            FROM company_prospect_evidence cpe
            JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
            LEFT JOIN source_documents sd ON cpe.source_document_id = sd.id
            WHERE cpe.source_document_id IS NOT NULL
            LIMIT 5
        """)
        
        print(f"Linkage quality check (first 5):")
        for row in linkage_check:
            tenant_ok = row['cpe_tenant'] == row['cp_tenant'] == row['sd_tenant']
            run_ok = row['cp_run'] == row['sd_run']
            print(f"  {str(row['id'])[:8]}... tenant_ok={tenant_ok}, run_ok={run_ok}, url_match={row['url_match']}")
    
    # Check evidence URLs vs source document URLs
    evidence_urls = await conn.fetch("SELECT DISTINCT source_url FROM company_prospect_evidence WHERE source_url IS NOT NULL LIMIT 5")
    sd_urls = await conn.fetch("SELECT DISTINCT url FROM source_documents WHERE url IS NOT NULL LIMIT 5") 
    
    print(f"Sample evidence URLs:")
    for row in evidence_urls:
        print(f"  {row['source_url'][:60]}...")
    
    print(f"Sample SD URLs:")
    for row in sd_urls:
        print(f"  {row['url'][:60]}...")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
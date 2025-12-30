#!/usr/bin/env python3
"""Analyze cardinality patterns to harden constraints."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncio
import asyncpg

async def main():
    """Analyze cardinality to determine proper constraints."""
    
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ats_db"
    conn = await asyncpg.connect(DATABASE_URL)
    
    print("=== CARDINALITY ANALYSIS FOR CONSTRAINT HARDENING ===")
    
    # 1. Evidence per prospect patterns
    prospect_evidence = await conn.fetch("""
        SELECT 
            company_prospect_id,
            COUNT(*) as evidence_count,
            COUNT(DISTINCT source_document_id) as unique_sources,
            COUNT(DISTINCT source_type) as unique_types
        FROM company_prospect_evidence 
        GROUP BY company_prospect_id
        ORDER BY evidence_count DESC
        LIMIT 10
    """)
    
    print("Evidence per prospect (top 10):")
    for row in prospect_evidence:
        print(f"  Prospect {str(row['company_prospect_id'])[:8]}... {row['evidence_count']} evidence, {row['unique_sources']} sources, {row['unique_types']} types")
    
    # 2. Evidence per source document patterns
    source_evidence = await conn.fetch("""
        SELECT 
            source_document_id,
            COUNT(*) as evidence_count,
            COUNT(DISTINCT company_prospect_id) as unique_prospects
        FROM company_prospect_evidence 
        WHERE source_document_id IS NOT NULL
        GROUP BY source_document_id
        ORDER BY evidence_count DESC
        LIMIT 10
    """)
    
    print("\nEvidence per source document (top 10):")
    for row in source_evidence:
        doc_id = str(row['source_document_id'])[:8] if row['source_document_id'] else 'None'
        print(f"  Source {doc_id}... {row['evidence_count']} evidence, {row['unique_prospects']} prospects")
    
    # 3. Duplicate analysis
    duplicates = await conn.fetch("""
        SELECT 
            tenant_id,
            company_prospect_id,
            source_document_id,
            source_type,
            source_name,
            COUNT(*) as count
        FROM company_prospect_evidence
        GROUP BY tenant_id, company_prospect_id, source_document_id, source_type, source_name
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    """)
    
    print(f"\nDuplicate violations of new constraint: {len(duplicates)}")
    if len(duplicates) > 0:
        print("Top duplicates:")
        for i, row in enumerate(duplicates[:5]):
            prospect_id = str(row['company_prospect_id'])[:8]
            source_id = str(row['source_document_id'])[:8] if row['source_document_id'] else 'None'
            print(f"  {i+1}. Prospect {prospect_id}, Source {source_id}, Type {row['source_type']}, Count {row['count']}")
    
    # 4. NULL analysis for potential NOT NULL constraints
    null_analysis = await conn.fetchrow("""
        SELECT 
            COUNT(*) as total,
            COUNT(source_document_id) as has_source_doc,
            COUNT(source_content_hash) as has_content_hash,
            COUNT(source_url) as has_source_url,
            COUNT(raw_snippet) as has_raw_snippet,
            COUNT(list_name) as has_list_name,
            COUNT(search_query_used) as has_search_query
        FROM company_prospect_evidence
    """)
    
    print(f"\nNULL analysis:")
    print(f"  Total records: {null_analysis['total']}")
    print(f"  Has source_document_id: {null_analysis['has_source_doc']} ({100*null_analysis['has_source_doc']/null_analysis['total']:.1f}%)")
    print(f"  Has source_content_hash: {null_analysis['has_content_hash']} ({100*null_analysis['has_content_hash']/null_analysis['total']:.1f}%)")
    print(f"  Has source_url: {null_analysis['has_source_url']} ({100*null_analysis['has_source_url']/null_analysis['total']:.1f}%)")
    print(f"  Has raw_snippet: {null_analysis['has_raw_snippet']} ({100*null_analysis['has_raw_snippet']/null_analysis['total']:.1f}%)")
    print(f"  Has list_name: {null_analysis['has_list_name']} ({100*null_analysis['has_list_name']/null_analysis['total']:.1f}%)")
    print(f"  Has search_query: {null_analysis['has_search_query']} ({100*null_analysis['has_search_query']/null_analysis['total']:.1f}%)")
    
    # 5. Check constraint violations in current data
    constraint_violations = await conn.fetch("""
        SELECT 
            'missing_source_when_linked' as violation_type,
            COUNT(*) as count
        FROM company_prospect_evidence
        WHERE source_document_id IS NOT NULL AND (source_url IS NULL OR source_content_hash IS NULL)
        
        UNION ALL
        
        SELECT 
            'orphaned_hash_without_doc' as violation_type,
            COUNT(*) as count
        FROM company_prospect_evidence
        WHERE source_document_id IS NULL AND source_content_hash IS NOT NULL
    """)
    
    print(f"\nConstraint violation candidates:")
    for row in constraint_violations:
        print(f"  {row['violation_type']}: {row['count']} records")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
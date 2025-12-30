#!/usr/bin/env python3
"""
Script to manually clean up duplicate source documents to enable run-scoped unique constraint.

This script:
1. Identifies duplicate source documents (same tenant_id, company_research_run_id, content_hash)
2. Updates foreign key references to point to the canonical (oldest) record
3. Deletes the duplicate records
4. Applies the run-scoped unique constraint
"""

import asyncio
import os
import sys
from uuid import UUID

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.db.session import async_session_maker
from sqlalchemy import text

async def cleanup_source_document_duplicates():
    """Clean up duplicate source documents and apply unique constraint."""
    
    async with async_session_maker() as db:
        print("Starting source document duplicate cleanup...")
        
        # Step 1: Identify duplicates
        print("1. Identifying duplicates...")
        duplicate_query = text("""
            WITH duplicates AS (
                SELECT id,
                       tenant_id,
                       company_research_run_id,
                       content_hash,
                       created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, company_research_run_id, content_hash 
                           ORDER BY created_at
                       ) as row_num
                FROM source_documents
                WHERE company_research_run_id IS NOT NULL
            )
            SELECT tenant_id, company_research_run_id, content_hash, COUNT(*) as dup_count
            FROM duplicates
            GROUP BY tenant_id, company_research_run_id, content_hash
            HAVING COUNT(*) > 1
        """)
        
        duplicate_result = await db.execute(duplicate_query)
        duplicate_sets = duplicate_result.fetchall()
        
        print(f"Found {len(duplicate_sets)} duplicate sets:")
        for i, dup_set in enumerate(duplicate_sets):
            print(f"  Row {i}: {dup_set}")
            try:
                tenant_id, run_id, content_hash, dup_count = dup_set
                print(f"  - Tenant: {tenant_id}, Run: {run_id}, Hash: {content_hash[:8] if content_hash else 'None'}..., Count: {dup_count}")
            except Exception as e:
                print(f"  Error unpacking: {e}")
        
        if not duplicate_sets:
            print("No duplicates found. Proceeding to apply constraint...")
            await apply_unique_constraint(db)
            return
        
        # Step 2: Update foreign key references for NULL content_hash duplicates
        print("2a. Updating foreign key references for NULL content_hash duplicates...")
        
        update_null_fks_query = text("""
            WITH duplicates AS (
                SELECT id,
                       tenant_id,
                       company_research_run_id,
                       content_hash,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, company_research_run_id, content_hash 
                           ORDER BY created_at
                       ) as row_num
                FROM source_documents
                WHERE company_research_run_id IS NOT NULL
                AND content_hash IS NULL
            ),
            canonical_mapping AS (
                SELECT 
                    dup.id as duplicate_id,
                    canonical.id as canonical_id
                FROM duplicates dup
                JOIN duplicates canonical ON (
                    dup.tenant_id = canonical.tenant_id AND
                    dup.company_research_run_id = canonical.company_research_run_id AND
                    (dup.content_hash IS NULL AND canonical.content_hash IS NULL) AND
                    canonical.row_num = 1
                )
                WHERE dup.row_num > 1
            )
            UPDATE company_metrics 
            SET source_document_id = cm.canonical_id
            FROM canonical_mapping cm
            WHERE company_metrics.source_document_id = cm.duplicate_id
        """)
        
        null_fk_result = await db.execute(update_null_fks_query)
        print(f"Updated {null_fk_result.rowcount} company_metrics FK references for NULL hash duplicates")
        
        # Step 2b: Update foreign key references for non-NULL content_hash duplicates
        print("2b. Updating foreign key references for non-NULL content_hash duplicates...")
        
        update_fks_query = text("""
            WITH duplicates AS (
                SELECT id,
                       tenant_id,
                       company_research_run_id,
                       content_hash,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, company_research_run_id, content_hash 
                           ORDER BY created_at
                       ) as row_num
                FROM source_documents
                WHERE company_research_run_id IS NOT NULL
                AND content_hash IS NOT NULL
            ),
            canonical_mapping AS (
                SELECT 
                    dup.id as duplicate_id,
                    canonical.id as canonical_id
                FROM duplicates dup
                JOIN duplicates canonical ON (
                    dup.tenant_id = canonical.tenant_id AND
                    dup.company_research_run_id = canonical.company_research_run_id AND
                    dup.content_hash = canonical.content_hash AND
                    canonical.row_num = 1
                )
                WHERE dup.row_num > 1
            )
            UPDATE company_metrics 
            SET source_document_id = cm.canonical_id
            FROM canonical_mapping cm
            WHERE company_metrics.source_document_id = cm.duplicate_id
        """)
        
        fk_update_result = await db.execute(update_fks_query)
        print(f"Updated {fk_update_result.rowcount} company_metrics FK references for hash duplicates")
        
        # Commit FK updates before deleting
        await db.commit()
        print("FK updates committed")
        
        # Step 3: Delete duplicates
        print("3. Deleting duplicate records...")
        
        delete_duplicates_query = text("""
            WITH duplicates AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, company_research_run_id, content_hash 
                           ORDER BY created_at
                       ) as row_num
                FROM source_documents
                WHERE company_research_run_id IS NOT NULL
            )
            DELETE FROM source_documents 
            WHERE id IN (
                SELECT id FROM duplicates WHERE row_num > 1
            )
        """)
        
        delete_result = await db.execute(delete_duplicates_query)
        print(f"Deleted {delete_result.rowcount} duplicate source document records")
        
        # Step 4: Delete NULL company_research_run_id records
        print("4. Cleaning up NULL company_research_run_id records...")
        null_cleanup_result = await db.execute(text("""
            DELETE FROM source_documents 
            WHERE company_research_run_id IS NULL
        """))
        print(f"Deleted {null_cleanup_result.rowcount} NULL company_research_run_id records")
        
        # Commit the cleanup changes
        await db.commit()
        
        # Step 5: Apply unique constraint
        print("5. Applying run-scoped unique constraint...")
        await apply_unique_constraint(db)


async def apply_unique_constraint(db):
    """Apply the unique constraint and make company_research_run_id NOT NULL."""
    
    # Make company_research_run_id NOT NULL
    print("Making company_research_run_id NOT NULL...")
    await db.execute(text("""
        ALTER TABLE source_documents 
        ALTER COLUMN company_research_run_id SET NOT NULL
    """))
    
    # Add unique constraint
    print("Adding run-scoped unique constraint...")
    await db.execute(text("""
        ALTER TABLE source_documents 
        ADD CONSTRAINT uq_source_documents_run_scoped 
        UNIQUE (tenant_id, company_research_run_id, content_hash)
    """))
    
    await db.commit()
    print("SUCCESS: Run-scoped unique constraint applied!")


async def main():
    """Main cleanup function."""
    try:
        await cleanup_source_document_duplicates()
        print("Cleanup completed successfully!")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
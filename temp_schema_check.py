#!/usr/bin/env python3
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine

async def check_schema():
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://ats_user:ats_password@localhost/ats_db")
    engine = create_async_engine(DATABASE_URL)
    
    async with engine.connect() as conn:
        # Check company_prospect_evidence structure
        result = await conn.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'company_prospect_evidence'
            ORDER BY ordinal_position;
        """)
        print("=== company_prospect_evidence columns ===")
        for row in result:
            print(f"{row[0]}: {row[1]} {'NULL' if row[2] == 'YES' else 'NOT NULL'} {row[3] or ''}")
        
        print("\n=== source_documents columns ===")
        result = await conn.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'source_documents'
            ORDER BY ordinal_position;
        """)
        for row in result:
            print(f"{row[0]}: {row[1]} {'NULL' if row[2] == 'YES' else 'NOT NULL'} {row[3] or ''}")
        
        print("\n=== company_prospect_evidence indexes ===")
        result = await conn.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'company_prospect_evidence';
        """)
        for row in result:
            print(f"{row[0]}: {row[1]}")
        
        print("\n=== company_prospect_evidence constraints ===")
        result = await conn.execute("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint 
            WHERE conrelid = 'company_prospect_evidence'::regclass;
        """)
        for row in result:
            print(f"{row[0]} ({row[1]}): {row[2]}")
        
        print("\n=== Evidence linkage statistics ===")
        result = await conn.execute("""
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN source_document_id IS NULL THEN 1 ELSE 0 END) AS null_sd_id,
                SUM(CASE WHEN source_content_hash IS NULL THEN 1 ELSE 0 END) AS null_hash
            FROM company_prospect_evidence;
        """)
        row = result.fetchone()
        print(f"Total: {row[0]}, Null source_document_id: {row[1]}, Null source_content_hash: {row[2]}")
        
        if row[1] > 0 or row[2] > 0:
            print("\n=== Offending rows (10 samples) ===")
            result = await conn.execute("""
                SELECT id, tenant_id, company_prospect_id, source_document_id, source_content_hash
                FROM company_prospect_evidence 
                WHERE source_document_id IS NULL OR source_content_hash IS NULL
                LIMIT 10;
            """)
            for row in result:
                print(f"ID: {row[0]}, Tenant: {row[1]}, Prospect: {row[2]}, SD_ID: {row[3]}, Hash: {row[4]}")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_schema())
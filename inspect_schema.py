#!/usr/bin/env python3

import os
import psycopg2
from dotenv import load_dotenv

def inspect_schema():
    load_dotenv()
    
    # Connect to database
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', 5432),
        database=os.getenv('DB_NAME', 'ats_db'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgres')
    )
    cur = conn.cursor()
    cur = conn.cursor()
    
    try:
        # Check current evidence table structure
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'company_prospect_evidence' 
            ORDER BY ordinal_position
        """)
        
        print("=== COMPANY_PROSPECT_EVIDENCE COLUMNS ===")
        for col in cur.fetchall():
            print(f"{col[0]}: {col[1]} (nullable: {col[2]}) default: {col[3]}")
            
        # Check foreign key constraints 
        cur.execute("""
            SELECT 
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc 
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' 
                AND tc.table_name = 'company_prospect_evidence'
        """)
        
        print("\n=== FOREIGN KEY CONSTRAINTS ===")
        for row in cur.fetchall():
            print(f"{row[0]}: {row[1]} -> {row[2]}.{row[3]}")
            
        # Check unique constraints
        cur.execute("""
            SELECT 
                tc.constraint_name,
                kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'UNIQUE' 
                AND tc.table_name = 'company_prospect_evidence'
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """)
        
        print("\n=== UNIQUE CONSTRAINTS ===")
        constraints = {}
        for row in cur.fetchall():
            if row[0] not in constraints:
                constraints[row[0]] = []
            constraints[row[0]].append(row[1])
            
        for constraint_name, columns in constraints.items():
            print(f"{constraint_name}: ({', '.join(columns)})")

        # Check for any existing evidence-source document links
        cur.execute("""
            SELECT COUNT(*) as total_evidence,
                   COUNT(source_document_id) as linked_evidence
            FROM company_prospect_evidence
        """)
        
        row = cur.fetchone()
        print(f"\n=== CURRENT LINKAGE STATUS ===")
        print(f"Total evidence records: {row[0]}")
        print(f"Records with source_document_id: {row[1]}")
        
        # Sample data relationships
        cur.execute("""
            SELECT 
                cpe.id as evidence_id,
                cpe.tenant_id as cpe_tenant_id,
                cpe.source_document_id,
                cpe.source_content_hash,
                cp.id as prospect_id,
                cp.tenant_id as cp_tenant_id,
                cp.company_research_run_id,
                sd.id as source_doc_id,
                sd.tenant_id as sd_tenant_id,
                sd.content_hash as sd_content_hash
            FROM company_prospect_evidence cpe
            LEFT JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
            LEFT JOIN source_documents sd ON cpe.source_document_id = sd.id
            LIMIT 5
        """)
        
        print(f"\n=== RELATIONSHIP SAMPLE ===")
        for row in cur.fetchall():
            print(f"Evidence {row[0]}:")
            print(f"  CPE tenant: {row[1]}")
            print(f"  CP tenant: {row[5]} | CP run: {row[6]}")
            print(f"  SD tenant: {row[8]}")
            print(f"  Content hash match: {row[3] == row[9] if row[3] and row[9] else 'N/A'}")
            print()
            
        # Check source_documents table structure to understand linkage
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'source_documents' 
            ORDER BY ordinal_position
        """)
        
        print(f"\n=== SOURCE_DOCUMENTS COLUMNS ===")
        for col in cur.fetchall():
            print(f"{col[0]}: {col[1]} (nullable: {col[2]})")
            
        # Check for tenant/run violations
        cur.execute("""
            SELECT 
                COUNT(*) as violations,
                COUNT(DISTINCT cpe.tenant_id) as distinct_cpe_tenants,
                COUNT(DISTINCT cp.tenant_id) as distinct_cp_tenants,
                COUNT(DISTINCT sd.tenant_id) as distinct_sd_tenants
            FROM company_prospect_evidence cpe
            LEFT JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
            LEFT JOIN source_documents sd ON cpe.source_document_id = sd.id
            WHERE cpe.source_document_id IS NOT NULL
            AND (cpe.tenant_id != cp.tenant_id OR cp.tenant_id != sd.tenant_id)
        """)
        
        row = cur.fetchone()
        print(f"\n=== TENANT CONSISTENCY CHECK ===")
        print(f"Tenant violations: {row[0]}")
        print(f"Distinct CPE tenants: {row[1]}")
        print(f"Distinct CP tenants: {row[2]}")  
        print(f"Distinct SD tenants: {row[3]}")
            
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    inspect_schema()
#!/usr/bin/env python3
"""
Evidence Query Tool
Queries evidence for a specific tenant and company research run.
"""

import psycopg2
import sys

# Database configuration
DSN = "postgresql://postgres:postgres@localhost:5432/ats_db"

# Target IDs
TENANT_ID = "33333333-3333-3333-3333-333333333333"
RUN_ID = "1301c5ca-09d7-4f73-babb-458f4855dd1f"

def main():
    try:
        # Connect to database
        conn = psycopg2.connect(DSN)
        cur = conn.cursor()

        print("=== EVIDENCE QUERY RESULTS ===")
        print(f"Tenant ID: {TENANT_ID}")
        print(f"Company Research Run ID: {RUN_ID}")
        print()

        # Query latest evidence row
        cur.execute('''
            SELECT cpe.id, cpe.source_type, cpe.source_name, cpe.raw_snippet, 
                   cpe.evidence_weight, cp.name_raw, cpe.created_at
            FROM company_prospect_evidence cpe
            JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
            WHERE cp.tenant_id = %s
              AND cp.company_research_run_id = %s
            ORDER BY cpe.created_at DESC
            LIMIT 1
        ''', (TENANT_ID, RUN_ID))

        row = cur.fetchone()
        print("=== LATEST EVIDENCE ROW ===")
        if row:
            print(f"Evidence ID: {row[0]}")
            print(f"Source Type: {row[1]}")
            print(f"Source Name: {row[2]}")
            print(f"Raw Snippet: {row[3]}")
            print(f"Evidence Weight: {row[4]}")
            print(f"Company Name: {row[5]}")
            print(f"Created At: {row[6]}")
        else:
            print("No evidence found")

        print()

        # Query evidence count
        cur.execute('''
            SELECT COUNT(*)
            FROM company_prospect_evidence cpe
            JOIN company_prospects cp ON cpe.company_prospect_id = cp.id
            WHERE cp.tenant_id = %s
              AND cp.company_research_run_id = %s
        ''', (TENANT_ID, RUN_ID))

        count = cur.fetchone()[0]
        print("=== EVIDENCE COUNT ===")
        print(f"Total evidence records for run: {count}")

        # Close connection
        cur.close()
        conn.close()
        
        print("\n=== CONNECTION INFO ===")
        print(f"Database DSN: {DSN}")
        print("Connection successful!")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
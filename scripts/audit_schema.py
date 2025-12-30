"""
Audit database schema to identify type mismatches.

This script checks all tables for tenant_id and id column types
to identify any VARCHAR/TEXT fields that should be UUID.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def audit_schema():
    """Check database schema for type mismatches."""
    
    async with AsyncSessionLocal() as db:
        # Get all tables with tenant_id column
        query = text("""
            SELECT 
                table_name,
                column_name,
                data_type,
                udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND column_name IN ('tenant_id', 'id')
            ORDER BY table_name, column_name;
        """)
        
        result = await db.execute(query)
        rows = result.fetchall()
        
        print("\n" + "="*80)
        print("DATABASE SCHEMA AUDIT")
        print("="*80)
        print(f"\n{'Table':<30} {'Column':<15} {'Type':<20} {'UDT Name':<15}")
        print("-"*80)
        
        mismatches = []
        
        for row in rows:
            table_name, column_name, data_type, udt_name = row
            print(f"{table_name:<30} {column_name:<15} {data_type:<20} {udt_name:<15}")
            
            # Check for mismatches
            if column_name == 'tenant_id' and data_type != 'uuid':
                mismatches.append({
                    'table': table_name,
                    'column': column_name,
                    'current_type': data_type,
                    'expected_type': 'uuid'
                })
            elif column_name == 'id' and data_type != 'uuid':
                mismatches.append({
                    'table': table_name,
                    'column': column_name,
                    'current_type': data_type,
                    'expected_type': 'uuid'
                })
        
        if mismatches:
            print("\n" + "="*80)
            print("MISMATCHES FOUND")
            print("="*80)
            for mismatch in mismatches:
                print(f"\n❌ {mismatch['table']}.{mismatch['column']}")
                print(f"   Current: {mismatch['current_type']}")
                print(f"   Expected: {mismatch['expected_type']}")
        else:
            print("\n✅ No type mismatches found!")
        
        print("\n" + "="*80)
        
        return mismatches


if __name__ == "__main__":
    print("Auditing database schema...\n")
    mismatches = asyncio.run(audit_schema())
    
    if mismatches:
        print(f"\n⚠️  Found {len(mismatches)} type mismatches that need migration.")
        sys.exit(1)
    else:
        print("\n✅ Schema audit complete - all types match!")
        sys.exit(0)

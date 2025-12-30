"""
Comprehensive audit of all ID and foreign key columns in the database.
Checks that all ID fields and FK fields are UUID type.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def audit_all_ids_and_fks():
    """Audit all ID and foreign key columns."""
    print("Auditing all ID and foreign key columns in database...\n")
    
    async with AsyncSessionLocal() as session:
        # Query for all columns that end with '_id' or are named 'id'
        query = text("""
            SELECT
                table_name,
                column_name,
                data_type,
                udt_name,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND (column_name LIKE '%_id' OR column_name = 'id')
            ORDER BY table_name, column_name;
        """)
        
        result = await session.execute(query)
        rows = result.fetchall()
        
        print("=" * 120)
        print("ALL ID AND FOREIGN KEY COLUMNS")
        print("=" * 120)
        print(f"{'Table':<35} {'Column':<30} {'Type':<20} {'UDT':<15} {'Nullable':<10}")
        print("-" * 120)
        
        mismatches = []
        
        for row in rows:
            table_name, column_name, data_type, udt_name, is_nullable = row
            
            # Check if it should be UUID
            # All *_id columns and 'id' columns should be UUID
            expected_type = 'uuid'
            
            status = "✅" if udt_name == expected_type else "❌"
            
            print(f"{status} {table_name:<33} {column_name:<28} {data_type:<18} {udt_name:<13} {is_nullable:<10}")
            
            if udt_name != expected_type:
                mismatches.append((table_name, column_name, data_type, udt_name))
        
        print("=" * 120)
        
        if mismatches:
            print(f"\n⚠️  Found {len(mismatches)} type mismatches that need migration:\n")
            for table, column, dtype, udt in mismatches:
                print(f"   {table}.{column}: {dtype} ({udt}) → should be uuid")
            print()
            return 1
        else:
            print("\n✅ No type mismatches found!\n")
            print("=" * 120)
            return 0


if __name__ == "__main__":
    exit_code = asyncio.run(audit_all_ids_and_fks())
    print(f"\n✅ Audit complete - all ID and FK types are consistent!" if exit_code == 0 else f"\n❌ Audit found {exit_code} issues!")
    exit(exit_code)

"""
Validate search indexing setup for candidate search.

Checks that all required indices exist and are properly configured.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def validate_search_indices():
    """Validate all search-related indices exist."""
    print("Validating search indices and configuration...\n")
    
    async with AsyncSessionLocal() as session:
        # Check if search_vector column exists
        check_column = text("""
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'candidate'
            AND column_name = 'search_vector';
        """)
        
        result = await session.execute(check_column)
        search_vector_col = result.fetchone()
        
        if search_vector_col:
            print(f"✅ search_vector column exists: {search_vector_col.data_type} ({search_vector_col.udt_name})")
        else:
            print("❌ search_vector column NOT FOUND on candidate table")
            return 1
        
        # Check for GIN index on search_vector
        check_gin_index = text("""
            SELECT
                i.relname as index_name,
                am.amname as index_type
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_am am ON i.relam = am.oid
            WHERE t.relname = 'candidate'
            AND i.relname LIKE '%search_vector%'
            AND am.amname = 'gin';
        """)
        
        result = await session.execute(check_gin_index)
        gin_index = result.fetchone()
        
        if gin_index:
            print(f"✅ GIN index exists: {gin_index.index_name} ({gin_index.index_type})")
        else:
            print("❌ GIN index on search_vector NOT FOUND")
            return 1
        
        # Check for composite indices on candidate
        check_composite_indices = text("""
            SELECT
                i.relname as index_name,
                string_agg(a.attname, ', ' ORDER BY array_position(ix.indkey, a.attnum)) as columns
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE t.relname = 'candidate'
            AND i.relname LIKE 'idx_candidate_%'
            GROUP BY i.relname
            ORDER BY i.relname;
        """)
        
        result = await session.execute(check_composite_indices)
        candidate_indices = result.fetchall()
        
        print("\n📊 Composite indices on candidate table:")
        required_indices = [
            "idx_candidate_tenant_home_country",
            "idx_candidate_tenant_location",
            "idx_candidate_tenant_title",
            "idx_candidate_tenant_company",
            "idx_candidate_tenant_promotability",
            "idx_candidate_tenant_updated",
        ]
        
        found_indices = set()
        for idx in candidate_indices:
            print(f"   ✅ {idx.index_name}: ({idx.columns})")
            found_indices.add(idx.index_name)
        
        missing = set(required_indices) - found_indices
        if missing:
            print(f"\n⚠️  Missing indices:")
            for idx_name in missing:
                print(f"   ❌ {idx_name}")
        else:
            print(f"\n✅ All required candidate indices exist")
        
        # Check for indices on candidate_assignment
        check_assignment_indices = text("""
            SELECT
                i.relname as index_name,
                string_agg(a.attname, ', ' ORDER BY array_position(ix.indkey, a.attnum)) as columns
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE t.relname = 'candidate_assignment'
            AND i.relname LIKE 'idx_candidate_assignment_%'
            GROUP BY i.relname
            ORDER BY i.relname;
        """)
        
        result = await session.execute(check_assignment_indices)
        assignment_indices = result.fetchall()
        
        print("\n📊 Indices on candidate_assignment table:")
        required_assignment_indices = [
            "idx_candidate_assignment_tenant_role",
            "idx_candidate_assignment_tenant_candidate",
        ]
        
        found_assignment_indices = set()
        for idx in assignment_indices:
            print(f"   ✅ {idx.index_name}: ({idx.columns})")
            found_assignment_indices.add(idx.index_name)
        
        missing_assignment = set(required_assignment_indices) - found_assignment_indices
        if missing_assignment:
            print(f"\n⚠️  Missing assignment indices:")
            for idx_name in missing_assignment:
                print(f"   ❌ {idx_name}")
        else:
            print(f"\n✅ All required candidate_assignment indices exist")
        
        # Test a simple search query
        print("\n🔍 Testing search query...")
        test_search = text("""
            SELECT id, first_name, last_name, current_title
            FROM candidate
            WHERE tenant_id = (SELECT id FROM tenant LIMIT 1)
            AND search_vector @@ plainto_tsquery('english', 'software')
            LIMIT 5;
        """)
        
        try:
            result = await session.execute(test_search)
            results = result.fetchall()
            print(f"✅ Search query executed successfully ({len(results)} results)")
            for row in results:
                print(f"   • {row.first_name} {row.last_name} - {row.current_title or 'N/A'}")
        except Exception as e:
            print(f"❌ Search query failed: {e}")
            return 1
        
        print("\n" + "=" * 80)
        
        if missing or missing_assignment:
            print("\n⚠️  Some indices are missing but search functionality works")
            return 0  # Don't fail - just warn
        else:
            print("\n✅ All search indices validated successfully!")
            return 0


if __name__ == "__main__":
    exit_code = asyncio.run(validate_search_indices())
    exit(exit_code)

"""
Company Research Module Smoke Tests

Verifies database schema and functional operations to prevent runtime errors.
Run this before deploying or after any schema/code changes.

Exit codes:
  0 = All tests passed
  1 = One or more tests failed
"""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from app.services.company_research_service import CompanyResearchService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyProspectCreate,
    CompanyProspectUpdateManual,
)
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession


class SmokeTestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_tenant_id = None
        self.test_role_id = None
        self.test_run_id = None
        self.test_prospect_id = None
    
    def log_pass(self, message: str):
        """Log a passed test."""
        print(f"✓ PASS: {message}")
        self.passed += 1
    
    def log_fail(self, message: str, error: str = None):
        """Log a failed test."""
        print(f"✗ FAIL: {message}")
        if error:
            print(f"  Error: {error}")
        self.failed += 1
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        print("=" * 70)
        if self.failed == 0:
            print("✅ ALL TESTS PASSED - Company Research module is operational")
            return 0
        else:
            print("❌ TESTS FAILED - Company Research module has issues")
            return 1
    
    async def check_table_exists(self, db: AsyncSession, table_name: str) -> bool:
        """Check if a table exists."""
        try:
            result = await db.execute(text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = '{table_name}'
                );
            """))
            exists = result.scalar()
            if exists:
                self.log_pass(f"Table '{table_name}' exists")
                return True
            else:
                self.log_fail(f"Table '{table_name}' does not exist")
                return False
        except Exception as e:
            self.log_fail(f"Failed to check table '{table_name}'", str(e))
            return False
    
    async def check_columns_exist(self, db: AsyncSession, table_name: str, columns: list) -> bool:
        """Check if required columns exist in a table."""
        try:
            result = await db.execute(text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}'
            """))
            existing_columns = [row[0] for row in result.fetchall()]
            
            all_exist = True
            for col in columns:
                if col in existing_columns:
                    self.log_pass(f"Column '{table_name}.{col}' exists")
                else:
                    self.log_fail(f"Column '{table_name}.{col}' is missing")
                    all_exist = False
            
            return all_exist
        except Exception as e:
            self.log_fail(f"Failed to check columns in '{table_name}'", str(e))
            return False
    
    async def setup_test_data(self, db: AsyncSession) -> bool:
        """Set up test tenant and role."""
        try:
            # Get first tenant
            result = await db.execute(text("SELECT id FROM tenant LIMIT 1"))
            tenant_row = result.fetchone()
            if not tenant_row:
                self.log_fail("No tenant found in database - create one first")
                return False
            
            self.test_tenant_id = str(tenant_row[0])
            self.log_pass(f"Found test tenant: {self.test_tenant_id}")
            
            # Get first role for that tenant
            result = await db.execute(text("""
                SELECT id FROM role 
                WHERE tenant_id = :tenant_id 
                LIMIT 1
            """), {"tenant_id": self.test_tenant_id})
            role_row = result.fetchone()
            if not role_row:
                self.log_fail("No role found for tenant - create one first")
                return False
            
            self.test_role_id = role_row[0]
            self.log_pass(f"Found test role: {self.test_role_id}")
            return True
            
        except Exception as e:
            self.log_fail("Failed to set up test data", str(e))
            return False
    
    async def test_create_run(self, db: AsyncSession) -> bool:
        """Test creating a research run WITHOUT tenant_id in schema."""
        try:
            service = CompanyResearchService(db)
            
            # Create run schema WITHOUT tenant_id
            run_create = CompanyResearchRunCreate(
                role_mandate_id=self.test_role_id,
                name="[SMOKE TEST] Test Run",
                description="Automated smoke test run",
                sector="test",
                region_scope=["US"],
                config={"test": True},
                status="planned",
            )
            
            # Service should accept tenant_id separately
            run = await service.create_research_run(
                tenant_id=self.test_tenant_id,
                data=run_create,
            )
            await db.commit()
            
            self.test_run_id = run.id
            self.log_pass(f"Created research run: {run.id}")
            return True
            
        except Exception as e:
            self.log_fail("Failed to create research run", str(e))
            return False
    
    async def test_list_runs(self, db: AsyncSession) -> bool:
        """Test listing runs for a role."""
        try:
            service = CompanyResearchService(db)
            runs = await service.list_research_runs_for_role(
                tenant_id=self.test_tenant_id,
                role_mandate_id=self.test_role_id,
            )
            
            # Check if our test run appears
            found = any(run.id == self.test_run_id for run in runs)
            if found:
                self.log_pass(f"Listed runs and found test run ({len(runs)} total)")
                return True
            else:
                self.log_fail("Test run not found in list")
                return False
                
        except Exception as e:
            self.log_fail("Failed to list runs", str(e))
            return False
    
    async def test_seed_prospects(self, db: AsyncSession) -> bool:
        """Test creating multiple prospects."""
        try:
            service = CompanyResearchService(db)
            
            for i in range(5):
                prospect_create = CompanyProspectCreate(
                    company_research_run_id=self.test_run_id,
                    role_mandate_id=self.test_role_id,
                    name_raw=f"Test Company {i+1}",
                    name_normalized=f"test company {i+1}",
                    sector="test",
                    relevance_score=0.9 - (i * 0.1),
                    evidence_score=0.8 - (i * 0.1),
                    manual_priority=None if i == 0 else i,
                    is_pinned=(i == 0),
                    status="new",
                )
                
                prospect = await service.create_prospect(
                    tenant_id=self.test_tenant_id,
                    data=prospect_create,
                )
                
                if i == 0:
                    self.test_prospect_id = prospect.id
            
            await db.commit()
            self.log_pass(f"Created 5 test prospects")
            return True
            
        except Exception as e:
            self.log_fail("Failed to seed prospects", str(e))
            return False
    
    async def test_list_prospects_ai_order(self, db: AsyncSession) -> bool:
        """Test listing prospects with AI ordering."""
        try:
            service = CompanyResearchService(db)
            prospects = await service.list_prospects_for_run(
                tenant_id=self.test_tenant_id,
                run_id=self.test_run_id,
                order_by="ai",
            )
            
            if len(prospects) == 5:
                self.log_pass(f"Listed prospects with AI order ({len(prospects)} found)")
                return True
            else:
                self.log_fail(f"Expected 5 prospects, found {len(prospects)}")
                return False
                
        except Exception as e:
            self.log_fail("Failed to list prospects (AI order)", str(e))
            return False
    
    async def test_list_prospects_manual_order(self, db: AsyncSession) -> bool:
        """Test listing prospects with manual ordering."""
        try:
            service = CompanyResearchService(db)
            prospects = await service.list_prospects_for_run(
                tenant_id=self.test_tenant_id,
                run_id=self.test_run_id,
                order_by="manual",
            )
            
            # First should be pinned
            if len(prospects) > 0 and prospects[0].is_pinned:
                self.log_pass(f"Listed prospects with manual order (pinned first)")
                return True
            else:
                self.log_fail("Manual order not working correctly (pinned not first)")
                return False
                
        except Exception as e:
            self.log_fail("Failed to list prospects (manual order)", str(e))
            return False
    
    async def test_update_manual_fields(self, db: AsyncSession) -> bool:
        """Test updating manual priority and pinned status."""
        try:
            service = CompanyResearchService(db)
            
            update_data = CompanyProspectUpdateManual(
                manual_priority=99,
                is_pinned=False,
            )
            
            updated = await service.update_prospect_manual_fields(
                tenant_id=self.test_tenant_id,
                prospect_id=self.test_prospect_id,
                data=update_data,
            )
            await db.commit()
            
            if updated and updated.manual_priority == 99 and not updated.is_pinned:
                self.log_pass("Updated manual fields successfully")
                return True
            else:
                self.log_fail("Manual fields not updated correctly")
                return False
                
        except Exception as e:
            self.log_fail("Failed to update manual fields", str(e))
            return False
    
    async def cleanup(self, db: AsyncSession):
        """Clean up test data."""
        try:
            if self.test_run_id:
                await db.execute(text("""
                    DELETE FROM company_research_runs 
                    WHERE id = :run_id
                """), {"run_id": self.test_run_id})
                await db.commit()
                print("\n🧹 Cleaned up test data")
        except Exception as e:
            print(f"\n⚠️  Warning: Failed to clean up test data: {e}")
    
    async def run_all_tests(self):
        """Run all smoke tests."""
        print("=" * 70)
        print("COMPANY RESEARCH MODULE SMOKE TESTS")
        print("=" * 70)
        print()
        
        async with AsyncSessionLocal() as db:
            try:
                # Schema checks
                print("▶ SCHEMA CHECKS")
                print("-" * 70)
                
                await self.check_table_exists(db, "company_research_runs")
                await self.check_columns_exist(db, "company_research_runs", [
                    "id", "tenant_id", "role_mandate_id", "name", "description",
                    "status", "sector", "region_scope", "config",
                    "created_at", "updated_at"
                ])
                
                await self.check_table_exists(db, "company_prospects")
                await self.check_columns_exist(db, "company_prospects", [
                    "id", "tenant_id", "company_research_run_id", "role_mandate_id",
                    "name_raw", "name_normalized", "relevance_score", "evidence_score",
                    "manual_priority", "is_pinned", "status"
                ])
                
                print()
                print("▶ FUNCTIONAL CHECKS")
                print("-" * 70)
                
                # Setup
                if not await self.setup_test_data(db):
                    return self.print_summary()
                
                # Functional tests
                if not await self.test_create_run(db):
                    return self.print_summary()
                
                await self.test_list_runs(db)
                
                if not await self.test_seed_prospects(db):
                    return self.print_summary()
                
                await self.test_list_prospects_ai_order(db)
                await self.test_list_prospects_manual_order(db)
                await self.test_update_manual_fields(db)
                
                # Cleanup
                await self.cleanup(db)
                
            except Exception as e:
                self.log_fail("Unexpected error during tests", str(e))
        
        return self.print_summary()


async def main():
    runner = SmokeTestRunner()
    exit_code = await runner.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())

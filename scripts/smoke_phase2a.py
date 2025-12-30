"""
Smoke tests for Company Research Phase 2A - Source-driven discovery.

Tests source document management, company extraction, and processing pipeline.
"""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from app.services.company_research_service import CompanyResearchService
from app.services.company_extraction_service import CompanyExtractionService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from sqlalchemy import text


class SmokeTestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_run_id = None
        self.test_source_id = None
        self.tenant_id = None
        self.role_id = None
    
    def assert_pass(self, condition: bool, message: str):
        """Assert a condition and track results."""
        if condition:
            print(f"✓ PASS: {message}")
            self.passed += 1
        else:
            print(f"✗ FAIL: {message}")
            self.failed += 1
    
    async def run_all_tests(self):
        """Run all Phase 2A smoke tests."""
        async with AsyncSessionLocal() as db:
            print("=" * 70)
            print("COMPANY RESEARCH PHASE 2A SMOKE TESTS")
            print("=" * 70)
            
            # Schema checks
            print("\n>> SCHEMA CHECKS")
            print("-" * 70)
            await self.test_source_documents_table_exists(db)
            await self.test_research_events_table_exists(db)
            await self.test_source_documents_columns(db)
            await self.test_research_events_columns(db)
            
            # Setup: Get tenant and role
            print("\n>> TEST DATA SETUP")
            print("-" * 70)
            await self.setup_test_data(db)
            
            # Functional tests
            print("\n>> FUNCTIONAL TESTS - SOURCE MANAGEMENT")
            print("-" * 70)
            await self.test_create_research_run(db)
            await self.test_add_text_source(db)
            await self.test_add_url_source(db)
            await self.test_list_sources(db)
            
            print("\n>> FUNCTIONAL TESTS - COMPANY EXTRACTION")
            print("-" * 70)
            self.test_extract_company_names()
            await self.test_process_sources(db)
            await self.test_prospects_created(db)
            await self.test_evidence_created(db)
            await self.test_research_events_logged(db)
            
            # Cleanup
            print("\n>> CLEANUP")
            print("-" * 70)
            await self.cleanup_test_data(db)
            
            # Summary
            print("\n" + "=" * 70)
            print(f"RESULTS: {self.passed} passed, {self.failed} failed")
            print("=" * 70)
            
            if self.failed == 0:
                print("✅ ALL TESTS PASSED - Phase 2A is operational\n")
                return 0
            else:
                print("❌ TESTS FAILED - Phase 2A has issues\n")
                return 1
    
    async def test_source_documents_table_exists(self, db):
        """Check if source_documents table exists."""
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'source_documents'
            );
        """))
        exists = result.scalar()
        self.assert_pass(exists, "Table 'source_documents' exists")
    
    async def test_research_events_table_exists(self, db):
        """Check if research_events table exists."""
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'research_events'
            );
        """))
        exists = result.scalar()
        self.assert_pass(exists, "Table 'research_events' exists")
    
    async def test_source_documents_columns(self, db):
        """Check source_documents table has required columns."""
        result = await db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'source_documents'
        """))
        columns = {row[0] for row in result.fetchall()}
        
        required = [
            'id', 'tenant_id', 'company_research_run_id', 'source_type',
            'title', 'url', 'content_text', 'content_hash', 'status',
            'error_message', 'fetched_at', 'created_at', 'updated_at'
        ]
        
        for col in required:
            self.assert_pass(col in columns, f"Column 'source_documents.{col}' exists")
    
    async def test_research_events_columns(self, db):
        """Check research_events table has required columns."""
        result = await db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'research_events'
        """))
        columns = {row[0] for row in result.fetchall()}
        
        required = [
            'id', 'tenant_id', 'company_research_run_id', 'event_type',
            'status', 'input_json', 'output_json', 'error_message',
            'created_at', 'updated_at'
        ]
        
        for col in required:
            self.assert_pass(col in columns, f"Column 'research_events.{col}' exists")
    
    async def setup_test_data(self, db):
        """Get test tenant and role for running tests."""
        # Get a tenant
        result = await db.execute(text("SELECT id FROM tenant LIMIT 1"))
        tenant_row = result.first()
        if tenant_row:
            self.tenant_id = str(tenant_row[0])
            self.assert_pass(True, f"Found test tenant: {self.tenant_id}")
        else:
            self.assert_pass(False, "No tenant found in database")
            return
        
        # Get a role
        result = await db.execute(text("""
            SELECT id FROM role
            WHERE tenant_id = :tenant_id
            LIMIT 1
        """), {"tenant_id": self.tenant_id})
        role_row = result.first()
        if role_row:
            self.role_id = str(role_row[0])
            self.assert_pass(True, f"Found test role: {self.role_id}")
        else:
            self.assert_pass(False, "No role found for tenant")
    
    async def test_create_research_run(self, db):
        """Test creating a research run for testing."""
        service = CompanyResearchService(db)
        
        run = await service.create_research_run(
            tenant_id=self.tenant_id,
            data=CompanyResearchRunCreate(
                role_mandate_id=UUID(self.role_id),
                name="[SMOKE TEST Phase 2A] Test Run",
                description="Testing source-driven discovery",
                sector="technology",
                region_scope=["US", "UK"],
                status="active",
            ),
        )
        
        await db.commit()
        
        if run and run.id:
            self.test_run_id = str(run.id)
            self.assert_pass(True, f"Created test research run: {self.test_run_id}")
        else:
            self.assert_pass(False, "Failed to create research run")
    
    async def test_add_text_source(self, db):
        """Test adding a text source."""
        service = CompanyResearchService(db)
        
        sample_text = """
        Here are some interesting companies:
        
        Acme Corporation Inc - Leading provider of anvils and cartoon supplies
        Beta Technologies Ltd - Innovative software solutions
        Gamma Holdings PLC - Financial services group
        Delta Systems GmbH - Industrial automation specialist
        """
        
        source = await service.add_source(
            tenant_id=self.tenant_id,
            data=SourceDocumentCreate(
                company_research_run_id=UUID(self.test_run_id),
                source_type="text",
                title="Sample company list",
                content_text=sample_text,
            ),
        )
        
        await db.commit()
        
        if source and source.id:
            self.test_source_id = str(source.id)
            self.assert_pass(True, f"Added text source: {self.test_source_id}")
        else:
            self.assert_pass(False, "Failed to add text source")
    
    async def test_add_url_source(self, db):
        """Test adding a URL source."""
        service = CompanyResearchService(db)
        
        source = await service.add_source(
            tenant_id=self.tenant_id,
            data=SourceDocumentCreate(
                company_research_run_id=UUID(self.test_run_id),
                source_type="url",
                title="Example company directory",
                url="https://example.com/companies",
            ),
        )
        
        await db.commit()
        
        self.assert_pass(source is not None, "Added URL source")
    
    async def test_list_sources(self, db):
        """Test listing sources for a run."""
        service = CompanyResearchService(db)
        
        sources = await service.list_sources_for_run(
            tenant_id=self.tenant_id,
            run_id=UUID(self.test_run_id),
        )
        
        self.assert_pass(
            len(sources) >= 2,
            f"Listed sources for run ({len(sources)} found)"
        )
    
    def test_extract_company_names(self):
        """Test company name extraction logic."""
        extraction_service = CompanyExtractionService(None)
        
        text = """
        Acme Corporation Inc
        Beta Technologies Ltd
        Gamma Holdings PLC
        Delta Systems GmbH
        Random Text That Should Not Match
        """
        
        companies = extraction_service._extract_company_names(text)
        
        # Should find at least the companies with suffixes
        self.assert_pass(
            len(companies) >= 3,
            f"Extracted company names ({len(companies)} found)"
        )
        
        # Check normalization
        normalized = extraction_service._normalize_company_name("Acme Corporation Inc")
        self.assert_pass(
            "inc" not in normalized.lower(),
            "Company name normalization removes suffixes"
        )
    
    async def test_process_sources(self, db):
        """Test processing sources to extract companies."""
        extraction_service = CompanyExtractionService(db)
        
        result = await extraction_service.process_sources(
            tenant_id=self.tenant_id,
            run_id=UUID(self.test_run_id),
        )
        
        await db.commit()
        
        self.assert_pass(
            result['processed'] >= 1,
            f"Processed {result['processed']} sources"
        )
        self.assert_pass(
            result['companies_found'] >= 3,
            f"Found {result['companies_found']} companies"
        )
        self.assert_pass(
            result['companies_new'] >= 3,
            f"Created {result['companies_new']} new prospects"
        )
    
    async def test_prospects_created(self, db):
        """Test that prospects were created from sources."""
        service = CompanyResearchService(db)
        
        prospects = await service.list_prospects_for_run(
            tenant_id=self.tenant_id,
            run_id=UUID(self.test_run_id),
            order_by="ai",
            limit=100,
        )
        
        self.assert_pass(
            len(prospects) >= 3,
            f"Created prospects from sources ({len(prospects)} found)"
        )
        
        # Check that prospect has required fields
        if prospects:
            prospect = prospects[0]
            self.assert_pass(
                prospect.name_raw is not None,
                "Prospect has name_raw field"
            )
            self.assert_pass(
                prospect.name_normalized is not None,
                "Prospect has name_normalized field"
            )
    
    async def test_evidence_created(self, db):
        """Test that evidence was linked to prospects."""
        service = CompanyResearchService(db)
        
        prospects = await service.list_prospects_for_run(
            tenant_id=self.tenant_id,
            run_id=UUID(self.test_run_id),
            order_by="ai",
            limit=1,
        )
        
        if prospects:
            evidence_list = await service.list_evidence_for_prospect(
                tenant_id=self.tenant_id,
                prospect_id=prospects[0].id,
            )
            
            self.assert_pass(
                len(evidence_list) >= 1,
                f"Evidence created for prospect ({len(evidence_list)} found)"
            )
        else:
            self.assert_pass(False, "No prospects found to check evidence")
    
    async def test_research_events_logged(self, db):
        """Test that research events were logged."""
        service = CompanyResearchService(db)
        
        events = await service.list_events_for_run(
            tenant_id=self.tenant_id,
            run_id=UUID(self.test_run_id),
            limit=50,
        )
        
        self.assert_pass(
            len(events) >= 3,
            f"Research events logged ({len(events)} found)"
        )
        
        # Check for specific event types
        event_types = {event.event_type for event in events}
        self.assert_pass(
            'fetch' in event_types,
            "Fetch event logged"
        )
        self.assert_pass(
            'extract' in event_types,
            "Extract event logged"
        )
        self.assert_pass(
            'dedupe' in event_types,
            "Dedupe event logged"
        )
    
    async def cleanup_test_data(self, db):
        """Clean up test data."""
        if self.test_run_id:
            await db.execute(text("""
                DELETE FROM company_research_runs
                WHERE id = :run_id
            """), {"run_id": self.test_run_id})
            await db.commit()
            print("🧹 Cleaned up test data")


async def main():
    """Main test runner."""
    runner = SmokeTestRunner()
    exit_code = await runner.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())

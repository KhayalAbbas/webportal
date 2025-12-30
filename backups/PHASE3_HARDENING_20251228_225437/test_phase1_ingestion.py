"""
Test Phase 1 manual list ingestion.
This script simulates the user acceptance test.
"""

import httpx
import asyncio
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.server]

BASE_URL = "http://localhost:8000"

async def test_ingestion():
    """Test the manual list ingestion endpoint."""
    
    # First, we need to authenticate and get a session
    # For now, let's just print the test data
    
    list_a = """
    JPMorgan Chase & Co.
    Bank of America Corp
    Citigroup Inc.
    Wells Fargo & Company
    Goldman Sachs Group, Inc.
    Morgan Stanley
    HSBC Holdings plc
    """
    
    list_b = """
    Bank of America Corporation
    Citigroup Inc
    Wells Fargo
    Deutsche Bank AG
    Barclays PLC
    BNP Paribas SA
    """
    
    print("=" * 80)
    print("TEST: Phase 1 Manual List Ingestion")
    print("=" * 80)
    
    print("\nList A (7 lines):")
    print(list_a.strip())
    
    print("\nList B (6 lines):")
    print(list_b.strip())
    
    print("\n" + "=" * 80)
    print("EXPECTED OUTCOMES:")
    print("=" * 80)
    
    print("\n1. Normalization:")
    print("   - 'Bank of America Corp' → 'bank of america' (stripped 'corp')")
    print("   - 'Bank of America Corporation' → 'bank of america' (stripped 'corporation')")
    print("   - These should be treated as SAME canonical company")
    
    print("\n2. Deduplication within submission:")
    print("   - 'Citigroup Inc.' and 'Citigroup Inc' → 'citigroup' (same canonical)")
    print("   - 'Wells Fargo & Company' and 'Wells Fargo' → 'wells fargo' (same canonical)")
    
    print("\n3. Expected company count:")
    print("   - JPMorgan Chase: 1 (List A only)")
    print("   - Bank of America: 1 (Lists A+B, 2 evidences)")
    print("   - Citigroup: 1 (Lists A+B, 2 evidences)")
    print("   - Wells Fargo: 1 (Lists A+B, 2 evidences)")
    print("   - Goldman Sachs: 1 (List A only)")
    print("   - Morgan Stanley: 1 (List A only)")
    print("   - HSBC: 1 (List A only)")
    print("   - Deutsche Bank: 1 (List B only)")
    print("   - Barclays: 1 (List B only)")
    print("   - BNP Paribas: 1 (List B only)")
    print("   TOTAL: 10 unique companies")
    
    print("\n4. Evidence tracking:")
    print("   - Bank of America: 2 evidences (List A: 'Bank of America Corp', List B: 'Bank of America Corporation')")
    print("   - Citigroup: 2 evidences (List A: 'Citigroup Inc.', List B: 'Citigroup Inc')")
    print("   - Wells Fargo: 2 evidences (List A: 'Wells Fargo & Company', List B: 'Wells Fargo')")
    
    print("\n5. Statistics banner should show:")
    print("   - Parsed 13 lines (List A: 7, List B: 6)")
    print("   - Accepted 10 unique companies")
    print("   - 10 new, 0 existing")
    print("   - 3 duplicates within submission (2nd occurrences of BoA, Citi, WF)")
    
    print("\n" + "=" * 80)
    print("TO TEST MANUALLY:")
    print("=" * 80)
    print("1. Navigate to a research run detail page")
    print("2. Paste List A into first textarea")
    print("3. Paste List B into second textarea")
    print("4. Click 'Ingest Lists'")
    print("5. Verify banner message matches expected statistics")
    print("6. Verify table shows 10 companies with correct evidence counts")
    print("7. Refresh page - data should persist")
    print("8. Rerun ingestion - should show '0 new, 10 existing'")

if __name__ == "__main__":
    asyncio.run(test_ingestion())

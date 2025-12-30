"""
Test Wikipedia extraction with offline HTML content.
"""
import asyncio
from bs4 import BeautifulSoup
from app.services.company_extraction_service import CompanyExtractionService
from app.db.session import AsyncSessionLocal
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.db]

# Sample HTML from a Wikipedia-style banks page
sample_html = """
<html>
<body>
<div id="mw-content-text">
<h2>List of Banks</h2>
<table class="wikitable">
<tr><th>Bank Name</th><th>Type</th></tr>
<tr><td>Moldindconbank</td><td>Commercial</td></tr>
<tr><td>Moldova Agroindbank</td><td>Commercial</td></tr>
<tr><td>Victoriabank</td><td>Commercial</td></tr>
<tr><td>Mobiasbancă - Groupe Société Générale</td><td>Commercial</td></tr>
<tr><td>Banca Comercială Română Chișinău</td><td>Commercial</td></tr>
</table>
<h2>Former banks</h2>
<ul>
<li>Banca de Economii (closed 2015)</li>
<li>Banca Socială (closed 2015)</li>
<li>Unibank (closed 2015)</li>
</ul>
</div>
</body>
</html>
"""

async def test_offline_extraction():
    """Test Wikipedia extraction with offline HTML."""
    
    async with AsyncSessionLocal() as session:
        # Create service
        service = CompanyExtractionService(session)
        
        # Test extraction
        print("Testing Wikipedia structure extraction...")
        print(f"HTML length: {len(sample_html)} characters\n")
        
        extracted = service._extract_from_wikipedia(sample_html)
        
        print(f"Extracted {len(extracted)} items:")
        for i, item in enumerate(extracted, 1):
            print(f"  {i}. {item}")
        
        print(f"\nValidation:")
        invalid = [item for item in extracted if any(p in item.lower() for p in [
            'http', 'list of', 'company information from', 'wikipedia'
        ])]
        
        if invalid:
            print(f"  WARNING: {len(invalid)} items with invalid patterns")
        else:
            print(f"  OK: All items look valid")

if __name__ == "__main__":
    asyncio.run(test_offline_extraction())

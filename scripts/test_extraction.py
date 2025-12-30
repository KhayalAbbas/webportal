"""Test extraction logic directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.company_extraction_service import CompanyExtractionService

# Create a mock service just for testing the extraction
class MockDB:
    pass

service = CompanyExtractionService(MockDB())

# Test text 1: With bullet points
text1 = """Here are some interesting companies:
Acme Corporation Inc - Leading provider of anvils and cartoon supplies
Beta Technologies Ltd - Innovative software solutions
Gamma Holdings PLC - Financial services group
Delta Systems GmbH - Industrial automation specialist"""

print("Test 1: With suffixes")
print(f"Input:\n{text1}\n")
companies = service._extract_company_names(text1)
print(f"Found {len(companies)} companies:")
for name, snippet in companies:
    print(f"  - {name}")
print()

# Test text 2: With bullet points
text2 = """- Bajaj Finance Limited
- Shriram Finance Limited
- Cholamandalam Investment & Finance Company Limited
- Tata Capital Limited"""

print("Test 2: With bullet points")
print(f"Input:\n{text2}\n")
companies = service._extract_company_names(text2)
print(f"Found {len(companies)} companies:")
for name, snippet in companies:
    print(f"  - {name}")
print()

# Test text 3: Plain list
text3 = """Acme Corp
Beta Tech
Gamma Inc"""

print("Test 3: Plain list")
print(f"Input:\n{text3}\n")
companies = service._extract_company_names(text3)
print(f"Found {len(companies)} companies:")
for name, snippet in companies:
    print(f"  - {name}")

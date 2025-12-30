"""Test the simplified extraction logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.company_extraction_service import CompanyExtractionService

# Mock DB
class MockDB:
    pass

service = CompanyExtractionService(MockDB())

# Test 1: Simple list with bullets
test1 = """- Bajaj Finance Limited
- Shriram Finance Limited
- Cholamandalam Investment & Finance Company Limited
- Tata Capital Limited"""

print("=" * 60)
print("Test 1: Simple bullet list")
print("=" * 60)
print(f"Input:\n{test1}\n")
companies = service._extract_company_names(test1)
print(f"Extracted {len(companies)} companies:")
for name, snippet in companies:
    print(f"  • {name}")
print()

# Test 2: List with header
test2 = """Top NBFCs (sample list)
- Bajaj Finance Limited
- Shriram Finance Limited
- Cholamandalam Investment & Finance Company Limited"""

print("=" * 60)
print("Test 2: List with header")
print("=" * 60)
print(f"Input:\n{test2}\n")
companies = service._extract_company_names(test2)
print(f"Extracted {len(companies)} companies:")
for name, snippet in companies:
    print(f"  • {name}")
print()

# Test 3: Plain names without bullets
test3 = """Bajaj Finance Limited
Shriram Finance Limited
Cholamandalam Investment & Finance Company Limited"""

print("=" * 60)
print("Test 3: Plain names without bullets")
print("=" * 60)
print(f"Input:\n{test3}\n")
companies = service._extract_company_names(test3)
print(f"Extracted {len(companies)} companies:")
for name, snippet in companies:
    print(f"  • {name}")
print()

# Test 4: Mixed with short names
test4 = """- Acme Corp
- XYZ Ltd
- AB Inc"""

print("=" * 60)
print("Test 4: Short names")
print("=" * 60)
print(f"Input:\n{test4}\n")
companies = service._extract_company_names(test4)
print(f"Extracted {len(companies)} companies:")
for name, snippet in companies:
    print(f"  • {name}")
print()

# Test 5: With descriptions
test5 = """Bajaj Finance Limited - Financial services
Shriram Finance Limited - Asset financing
Cholamandalam Investment - Vehicle finance"""

print("=" * 60)
print("Test 5: With descriptions")
print("=" * 60)
print(f"Input:\n{test5}\n")
companies = service._extract_company_names(test5)
print(f"Extracted {len(companies)} companies:")
for name, snippet in companies:
    print(f"  • {name}")
    print(f"    Snippet: {snippet[:80]}")
print()

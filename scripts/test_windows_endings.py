"""Test with Windows line endings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.company_extraction_service import CompanyExtractionService

class MockDB:
    pass

service = CompanyExtractionService(MockDB())

# Actual text from user's failed source (with \r\n)
test_text = 'Bajaj Finance Limited\r\nShriram Finance Limited\r\nCholamandalam Investment & Finance Company Limited\r\nTata Capital Limited\r\nMahindra & Mahindra Financial Services Limited\r\nMuthoot Finance Limited\r\nL&T Finance Limited\r\nPiramal Capital & Housing Finance Limited'

print("="*70)
print("Test with Windows line endings (\\r\\n)")
print("="*70)
print(f"Input length: {len(test_text)}")
print(f"Repr: {repr(test_text[:100])}")
print()

companies = service._extract_company_names(test_text)
print(f"Extracted {len(companies)} companies:")
for i, (name, snippet) in enumerate(companies, 1):
    print(f"  {i}. {name}")

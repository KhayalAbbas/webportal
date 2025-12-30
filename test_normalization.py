"""
Unit test for Phase 1 ingestion normalization logic.
Tests the _normalize_company_name function.
"""

def _normalize_company_name(name: str) -> str:
    """
    Normalize company name for canonical identity matching.
    Strips legal suffixes, normalizes whitespace, lowercases.
    """
    if not name:
        return ""
    
    normalized = name.lower().strip()
    
    # Remove trailing punctuation first
    while normalized and normalized[-1] in '.,;:':
        normalized = normalized[:-1].strip()
    
    # Remove common legal suffixes (iterate to handle multiple)
    suffixes = [
        ' ltd', ' llc', ' plc', ' saog', ' sa', ' gmbh', ' ag',
        ' inc', ' corp', ' corporation', ' limited', ' group', ' holdings',
        ' company', ' co',
    ]
    
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
                changed = True
                break
        # Remove trailing punctuation after each suffix removal
        while normalized and normalized[-1] in '.,;:':
            normalized = normalized[:-1].strip()
            changed = True
    
    # Normalize whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized.strip()


def test_normalization():
    """Test normalization logic."""
    
    test_cases = [
        # Test case: (input, expected_output)
        ("JPMorgan Chase & Co.", "jpmorgan chase &"),
        ("Bank of America Corp", "bank of america"),
        ("Bank of America Corporation", "bank of america"),
        ("Citigroup Inc.", "citigroup"),
        ("Citigroup Inc", "citigroup"),
        ("Wells Fargo & Company", "wells fargo &"),
        ("Wells Fargo", "wells fargo"),
        ("Goldman Sachs Group, Inc.", "goldman sachs"),
        ("Morgan Stanley", "morgan stanley"),
        ("HSBC Holdings plc", "hsbc"),
        ("Deutsche Bank AG", "deutsche bank"),
        ("Barclays PLC", "barclays"),
        ("BNP Paribas SA", "bnp paribas"),
        ("Microsoft Corporation", "microsoft"),
        ("Microsoft Corp", "microsoft"),
        ("Microsoft Inc", "microsoft"),
        ("Apple Ltd", "apple"),
        ("Google LLC", "google"),
        ("Amazon Group", "amazon"),
        ("  Extra   Whitespace  Ltd  ", "extra whitespace"),
    ]
    
    print("=" * 80)
    print("NORMALIZATION TESTS")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for input_name, expected in test_cases:
        result = _normalize_company_name(input_name)
        status = "✓" if result == expected else "✗"
        
        if result == expected:
            passed += 1
            print(f"{status} '{input_name}' → '{result}'")
        else:
            failed += 1
            print(f"{status} '{input_name}'")
            print(f"  Expected: '{expected}'")
            print(f"  Got:      '{result}'")
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80)
    
    # Test deduplication examples
    print("\n" + "=" * 80)
    print("DEDUPLICATION EXAMPLES")
    print("=" * 80)
    
    examples = [
        ("Bank of America Corp", "Bank of America Corporation"),
        ("Citigroup Inc.", "Citigroup Inc"),
        ("Wells Fargo & Company", "Wells Fargo"),
        ("Microsoft Corp", "Microsoft Corporation", "Microsoft Inc"),
    ]
    
    for group in examples:
        normalized = [_normalize_company_name(name) for name in group]
        unique = set(normalized)
        
        print(f"\nInput variants: {len(group)}")
        for name in group:
            print(f"  - '{name}' → '{_normalize_company_name(name)}'")
        
        if len(unique) == 1:
            print(f"✓ All normalize to: '{list(unique)[0]}' (DEDUPLICATED)")
        else:
            print(f"✗ Multiple normalized forms: {unique} (NOT DEDUPLICATED)")


if __name__ == "__main__":
    test_normalization()

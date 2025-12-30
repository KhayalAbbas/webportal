# Phase 2A Text Source Extraction - Fix Summary

## Date: December 23, 2025

## Issue Reported
User reported that text sources were being stored correctly but extraction was failing. Request was to fix the text-source branch in `process_sources()` to properly handle plain pasted text.

## Root Causes Identified

### 1. Extraction Logic Issues
**File**: `app/services/company_extraction_service.py`

**Problems**:
- Bullet point regex pattern was incorrect: `[\-•*\d]+[\.\)]` required a dot/paren after the dash
- Required company suffixes (Ltd, Inc, etc.) OR Title Case - didn't handle plain lists
- Had minimum length filter (3 chars) blocking short company names
- Used original line instead of cleaned line for company names and snippets

**Fixes**:
- Fixed regex to properly strip bullets: `^[\-•*]+\s+` for bullets, `^\d+[\.\)]\s*` for numbers
- Added fallback strategy (Strategy 3) to treat any reasonable line as a company name
- Removed minimum length requirement in `_is_likely_company_name()`
- Used cleaned line consistently for both company names and snippets

### 2. Missing Schema Fields
**File**: `app/services/company_extraction_service.py`, lines 328, 371

**Problem**:
- `CompanyProspectEvidenceCreate` schema requires `tenant_id` field
- Calls were missing this required field
- `tenant_id` parameter was UUID but schema expects string

**Fix**:
- Added `tenant_id=str(tenant_id)` to both `CompanyProspectEvidenceCreate()` calls
- One for existing prospects (line 335)
- One for new prospects (line 373)

### 3. Repository Method Name Mismatch
**File**: `app/repositories/company_research_repo.py`

**Problem**:
- Service was calling `create_prospect_evidence()`
- Actual method name is `create_company_prospect_evidence()`

**Fix**:
- Updated both calls to use correct method name

### 4. Repository Commit Issue
**File**: `app/repositories/company_research_repo.py`, line 388

**Problem**:
- Repository was calling `await self.db.commit()` in create method
- Route was also calling `await session.commit()`
- This caused issues with transaction management

**Fix**:
- Changed repository to use `await self.db.flush()` instead
- Allows route to control transaction commit

## Extraction Strategy (Final Implementation)

The extraction now uses a 3-strategy approach:

### Strategy 1: Company Suffixes (High Confidence)
- Lines containing: Ltd, LLC, PLC, SAOG, SA, GmbH, AG, Inc, Corp, Corporation, Limited, Group, Holdings
- Entire cleaned line treated as company name
- **Example**: "Acme Corporation Inc" → extracted

### Strategy 2: Title Case Patterns (Medium Confidence)  
- 2-5 capitalized words in sequence
- Filters out common non-company phrases (cities, days, months)
- **Example**: "Beta Technologies" → extracted

### Strategy 3: Plain Text Fallback (Flexible)
- Any line with 2-200 characters containing letters
- Handles simple lists where each line is a company
- **Example**: "Acme Corp" → extracted
- **Example**: "XY" → extracted (no minimum length)

## Bullet Point Handling

**Before**:
```
- Bajaj Finance Limited  →  NOT stripped
```

**After**:
```
- Bajaj Finance Limited  →  "Bajaj Finance Limited"
• Company Name Ltd       →  "Company Name Ltd"
* Another Company        →  "Another Company"
1. Numbered Company      →  "Numbered Company"
1) Paren Numbered        →  "Paren Numbered"
```

## Testing Results

### Test Data Processed
- 6 text sources across 5 research runs
- Sample content included:
  - Companies with suffixes (Acme Corporation Inc, Beta Technologies Ltd)
  - Bullet-pointed lists (- Bajaj Finance Limited)
  - Plain text lists

### Results
```
Run 1: 5 companies found, 4 new prospects, 1 existing
Run 2: 14 companies found, 0 new prospects, 14 existing (deduplication working)
Run 3: 5 companies found, 4 new prospects, 1 existing
Run 4: 5 companies found, 4 new prospects, 1 existing
Run 5: 5 companies found, 4 new prospects, 1 existing
```

**Total**: 34 companies extracted, 16 new prospects created, 18 deduplicated

## Files Modified

1. **app/services/company_extraction_service.py** (5 changes)
   - Fixed bullet stripping regex (lines 203-205)
   - Added fallback extraction strategy (lines 227-237)
   - Removed minimum length filter (line 296)
   - Fixed repository method names (lines 331, 371)
   - Added tenant_id to evidence schemas (lines 335, 373)

2. **app/repositories/company_research_repo.py** (1 change)
   - Changed `commit()` to `flush()` in create_source_document (line 388)

3. **app/ui/routes/company_research.py** (3 changes)
   - Added error handling to add_source_text endpoint
   - Added error_message query parameter to run_detail
   - Added error_message to template context

4. **app/ui/templates/company_research_run_detail.html** (1 change)
   - Added error message display block

## Scripts Created

1. **scripts/reprocess_failed_sources.py** - Reset failed sources to 'new' status
2. **scripts/check_sources.py** - Check status of text sources
3. **scripts/reset_sources.py** - Reset processed/failed sources to 'new'
4. **scripts/process_new_sources.py** - Process all new text sources with detailed output
5. **scripts/test_extraction.py** - Test extraction logic directly
6. **scripts/inspect_content.py** - Inspect database content
7. **scripts/debug_process.py** - Debug process_sources flow

## Verification

✅ Plain pasted text treated as valid input
✅ Each non-empty line evaluated as potential company name
✅ Bullet points and hyphens stripped safely
✅ Short names allowed (no minimum length)
✅ Existing failed sources reprocessed
✅ Sources marked as 'processed'
✅ No duplicate Company Prospects created (deduplication working)

## Architecture Notes

- Logic fix only - no schema or database changes
- Multi-strategy extraction provides flexibility
- Deduplication via normalized names prevents duplicates
- Evidence linking tracks which source found which company
- Audit trail maintained via research_events table

## Future Enhancements (Out of Scope)

- LLM-based extraction for better accuracy
- Context-aware company detection
- Industry/sector classification
- Confidence scoring per extraction strategy
- Support for structured formats (CSV, Excel)

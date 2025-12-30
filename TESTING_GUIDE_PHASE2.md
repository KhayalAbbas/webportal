# Phase 2 Testing Guide

## Quick Start Test (5 minutes)

### Prerequisites
✅ Server is running on http://localhost:8000
✅ You have login credentials
✅ File `sample_ai_proposal.json` exists in C:\ATS

### Step-by-Step Test

#### 1. Login
- Open browser: http://localhost:8000
- Login with your credentials
- Navigate to "Company Research" page

#### 2. Create/Open Research Run
- Click "New Research Run" or open existing run
- You should see the run detail page

#### 3. Test Phase 1 (Baseline - Should Still Work)
- Find "Phase 1: Manual List Ingestion" section
- In **List A** textarea, paste:
  ```
  Apple Inc
  Microsoft Corporation
  Amazon.com, Inc.
  ```
- Click "Ingest Lists"
- **Expected**: 3 companies appear in table with List Sources "A"

#### 4. Test Phase 2 Validation
- Find "Phase 2: Ingest AI-Generated Proposal" section
- Open `sample_ai_proposal.json` in notepad
- Copy ALL content (Ctrl+A, Ctrl+C)
- Paste into the Phase 2 textarea
- Click **"✓ Validate (No Changes)"**
- **Expected**: Green box appears:
  ```
  ✅ Validation Passed!
  Companies: 5 | Metrics: 15 | Sources: 2
  ```

#### 5. Test Phase 2 Ingestion
- Click **"💾 Ingest Proposal"**
- Confirm the dialog
- **Expected**: Page reloads with success message at top
- **Expected**: Table now shows 8 companies total (3 from Phase 1 + 5 from Phase 2)

#### 6. Verify AI Data
Check the new companies show:
- ✅ **FAB**: AI Rank #1, AI Score 0.98, Primary Metric "AED 1.1B"
- ✅ **Emirates NBD**: AI Rank #2, AI Score 0.96, Primary Metric "AED 869.0B"
- ✅ **ADCB**: AI Rank #3, Primary Metric "AED 480.5B"
- ✅ **DIB**: AI Rank #4, Primary Metric "AED 345.2B"
- ✅ **Mashreq**: AI Rank #5, Primary Metric "AED 189.3B"

#### 7. Test Sorting
- **Sort by "AI Rank"**: FAB should be first (rank #1)
- **Sort by "Primary Metric (↓)"**: FAB should be first (highest assets)
- **Sort by "My Manual Order"**: Phase 1 companies mixed with Phase 2

#### 8. Test Manual Override
- Find **Emirates NBD** row
- In "My Rank" column, enter: `1`
- Click **Save** button
- Change sort to "My Manual Order"
- **Expected**: Emirates NBD jumps to top (user override)

#### 9. Test Idempotency
- Paste the same `sample_ai_proposal.json` again
- Click **Ingest Proposal**
- **Expected**: Success message, NO duplicates created
- **Expected**: Evidence count stays at 2 (not doubled to 4)

#### 10. Test Pin Functionality
- Click the "○" icon next to FAB
- **Expected**: Icon becomes "📌" and row turns yellow
- **Expected**: FAB stays at top regardless of sorting
- Click "📌" again to unpin

### Expected Final State

**Table should show 8 companies:**
1. **FAB** (Phase 2) - AI Rank #1, Assets AED 1.1B
2. **Emirates NBD** (Phase 2) - AI Rank #2, Assets AED 869.0B, My Rank 1
3. **ADCB** (Phase 2) - AI Rank #3
4. **DIB** (Phase 2) - AI Rank #4
5. **Mashreq** (Phase 2) - AI Rank #5
6. **Apple Inc** (Phase 1) - No AI rank, List Source A
7. **Microsoft Corporation** (Phase 1) - No AI rank, List Source A
8. **Amazon.com, Inc.** (Phase 1) - No AI rank, List Source A

## Troubleshooting

### Problem: Validation fails with "Invalid JSON"
**Solution**: Make sure you copied the ENTIRE content of sample_ai_proposal.json including opening `{` and closing `}`

### Problem: "Research run not found" error
**Solution**: Make sure you're on the run detail page (URL should be `/ui/company-research/runs/{some-uuid}`)

### Problem: No companies appear after ingestion
**Solution**: 
1. Check browser console for errors (F12)
2. Check terminal for server errors
3. Verify database migration was applied: `python -m alembic current`

### Problem: Sorting not working
**Solution**:
1. Refresh the page
2. Check that sorting dropdown is changing the URL parameter `?order_by=...`

### Problem: Server not starting
**Solution**:
```powershell
# Check if port 8000 is in use
Get-Process | Where-Object {$_.Port -eq 8000}

# Kill existing uvicorn processes
Get-Process uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force

# Restart server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Advanced Tests

### Test Invalid JSON
Paste this invalid JSON:
```json
{
  "query": "Test",
  "companies": []
}
```
**Expected**: Validation error: "companies list cannot be empty"

### Test Missing Required Fields
```json
{
  "query": "Test",
  "sources": [],
  "companies": [
    {
      "name": "Test Company"
    }
  ]
}
```
**Expected**: Validation error: "Field required: metrics"

### Test Duplicate Detection
1. Ingest sample_ai_proposal.json
2. Manually add "First Abu Dhabi Bank" to List A
3. Ingest List A
4. **Expected**: No duplicate created (normalization catches it)

### Test Alias Handling
1. Ingest sample_ai_proposal.json
2. Check database: `SELECT * FROM company_aliases;`
3. **Expected**: 6 aliases total (FAB, ENBD, etc.)

### Test Metric Storage
1. Ingest sample_ai_proposal.json
2. Check database: `SELECT * FROM company_metrics;`
3. **Expected**: 10 metrics (each bank has 2: total_assets in AED + USD)

## Database Verification (SQL)

```sql
-- Check prospects created
SELECT name_normalized, ai_rank, ai_score 
FROM company_prospects 
ORDER BY ai_rank NULLS LAST;

-- Check metrics
SELECT cp.name_normalized, cm.metric_key, cm.value_number, cm.value_currency
FROM company_metrics cm
JOIN company_prospects cp ON cm.company_prospect_id = cp.id
ORDER BY cp.ai_rank, cm.metric_key;

-- Check aliases
SELECT cp.name_normalized, ca.alias_name, ca.alias_type
FROM company_aliases ca
JOIN company_prospects cp ON ca.company_prospect_id = cp.id
ORDER BY cp.ai_rank;

-- Check sources
SELECT title, url, provider
FROM source_documents
WHERE source_type = 'ai_proposal';
```

## Performance Test

For larger datasets:
1. Create a JSON with 50+ companies
2. Ingest and measure time
3. **Expected**: <5 seconds for 50 companies

## Success Criteria Checklist

- [ ] Phase 1 still works (List A/B ingestion)
- [ ] Phase 2 form appears and is usable
- [ ] Validation catches errors before ingestion
- [ ] Ingestion creates companies with AI data
- [ ] Table shows new columns (Primary Metric, AI Rank, AI Score)
- [ ] Sorting by AI Rank works
- [ ] Sorting by Primary Metric works
- [ ] Manual override (My Rank) takes precedence
- [ ] Pin functionality works
- [ ] Idempotency works (no duplicates on re-ingest)
- [ ] No errors in browser console
- [ ] No errors in server terminal

---

**Status**: ✅ Ready for testing
**Time Required**: 5-10 minutes for full test
**Sample Data**: `sample_ai_proposal.json` (5 UAE banks)

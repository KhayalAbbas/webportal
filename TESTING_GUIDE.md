"""
QUICK START: Test Phase 1 Manual List Ingestion
================================================

Server Status: ✅ RUNNING (http://localhost:8000)

Step-by-Step Testing:
---------------------

1. OPEN BROWSER
   Navigate to: http://localhost:8000/ui/company-research

2. SELECT RESEARCH RUN
   - Click on "test1" run
   OR
   - Create a new research run

3. SCROLL TO INGESTION SECTION
   Look for: "Phase 1: Manual List Ingestion"
   You'll see two large textareas

4. PASTE TEST DATA

   📋 COPY THIS INTO "COMPANY LIST A":
   JPMorgan Chase & Co.
   Bank of America Corp
   Citigroup Inc.
   Wells Fargo & Company
   Goldman Sachs Group, Inc.
   Morgan Stanley
   HSBC Holdings plc

   📋 COPY THIS INTO "COMPANY LIST B":
   Bank of America Corporation
   Citigroup Inc
   Wells Fargo
   Deutsche Bank AG
   Barclays PLC
   BNP Paribas SA

5. CLICK BUTTON
   Click: "🚀 Ingest Lists"

6. VERIFY RESULTS
   ✅ Success banner should show:
      "Parsed 13 lines (List A: 7, List B: 6).
       Accepted 10 unique companies: 10 new, 0 existing, 
       3 duplicates within submission."

   ✅ Table should show 10 companies:
      - Bank of America: Evidence Count = 2, List Sources = "A, B"
      - Citigroup: Evidence Count = 2, List Sources = "A, B"
      - Wells Fargo: Evidence Count = 2, List Sources = "A, B"
      - JPMorgan Chase: Evidence Count = 1, List Sources = "A"
      - Goldman Sachs: Evidence Count = 1, List Sources = "A"
      - Morgan Stanley: Evidence Count = 1, List Sources = "A"
      - HSBC: Evidence Count = 1, List Sources = "A"
      - Deutsche Bank: Evidence Count = 1, List Sources = "B"
      - Barclays: Evidence Count = 1, List Sources = "B"
      - BNP Paribas: Evidence Count = 1, List Sources = "B"

7. TEST IDEMPOTENCY
   - Scroll back up to ingestion form
   - Paste SAME lists again
   - Click "🚀 Ingest Lists"
   
   ✅ Banner should now show:
      "Parsed 13 lines (List A: 7, List B: 6).
       Accepted 10 unique companies: 0 new, 10 existing,
       3 duplicates within submission."
   
   ✅ NO new companies should be created
   ✅ Company count remains 10

8. TEST PERSISTENCE
   - Refresh the page (F5)
   - Companies should still be visible
   - Evidence counts should be preserved

What You Should See:
-------------------

TABLE COLUMNS:
- 📌 (Pin icon) - for pinning companies to top
- Company Name - Normalized canonical name (e.g., "bank of america")
- Original Name - As you entered it (e.g., "Bank of America Corp")
- Evidence Count - Blue badge with number
- List Sources - Shows "A", "B", or "A, B"
- Status - Dropdown (new/approved/rejected/duplicate)
- My Rank - Manual priority number
- Actions - Save button

EVIDENCE TRACKING EXPLAINED:
- "Bank of America Corp" (List A) → normalized to "bank of america"
- "Bank of America Corporation" (List B) → normalized to "bank of america"
- Both become ONE company with TWO evidence records
- Evidence Count = 2
- List Sources = "A, B"

Why 10 Companies, Not 13?
-------------------------
Total lines: 13
Duplicates within submission: 3
- "Bank of America Corp" + "Bank of America Corporation" = 1 company
- "Citigroup Inc." + "Citigroup Inc" = 1 company  
- "Wells Fargo & Company" + "Wells Fargo" = 1 company

Unique companies: 13 - 3 = 10 ✓

Normalization Examples:
----------------------
Input                          → Normalized
"JPMorgan Chase & Co."         → "jpmorgan chase & co"
"Bank of America Corp"         → "bank of america"
"Bank of America Corporation"  → "bank of america" (same!)
"Wells Fargo & Company"        → "wells fargo & company"
"Wells Fargo"                  → "wells fargo" (different!)
"Goldman Sachs Group, Inc."    → "goldman sachs"
"HSBC Holdings plc"            → "hsbc"

Troubleshooting:
---------------

❌ "Research run not found"
   → Make sure you're logged in
   → Try creating a new research run

❌ Nothing happens when clicking button
   → Check browser console for errors (F12)
   → Verify server is running (check terminal)

❌ Companies not showing
   → Refresh the page
   → Check that lists have content (not blank)

❌ More than 10 companies created
   → Normalization might have failed
   → Check that legal suffixes are being stripped

Next Tests to Try:
-----------------

TEST 1: Single List
- Paste only in List A
- Leave List B empty
- Verify all companies show List Sources = "A"

TEST 2: Same Company, Different Variants
- List A: "Microsoft Corporation"
- List B: "Microsoft Corp"
- List B: "Microsoft Inc"
- Should create 1 company with 3 evidences

TEST 3: Empty Lines
- Add blank lines between company names
- Verify they are skipped (not counted as companies)

TEST 4: Special Characters
- Try: "AT&T Inc."
- Try: "Procter & Gamble Co."
- Verify normalization handles & correctly

TEST 5: Very Long Names
- Paste a company with 100+ character name
- Verify it's stored correctly (name_raw field is VARCHAR 255)

Success Criteria:
----------------
✅ Parsed count matches your line count
✅ Accepted count shows unique companies (after deduplication)
✅ Evidence counts are correct (1 for single list, 2 for both)
✅ List sources show correct letters (A, B, or A, B)
✅ Refresh persists data
✅ Rerun shows "0 new, N existing" (idempotent)
✅ No web calls made (check Network tab in browser)
✅ No garbage navigation items extracted

If all tests pass → Phase 1 implementation is COMPLETE! ✅

Questions or Issues?
-------------------
Check the detailed documentation in: PHASE1_IMPLEMENTATION.md
"""

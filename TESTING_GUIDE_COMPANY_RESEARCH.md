# Company Research Module - Complete Testing Guide

## ✅ Implementation Complete

### Backend (Already Done)
- ✅ Models: 4 tables (company_research_run, company_prospect, company_prospect_evidence, company_prospect_metric)
- ✅ Schemas: All Pydantic models for create/read/update operations
- ✅ Repository: Async CRUD with AI vs manual ordering
- ✅ Service: Business logic with validation
- ✅ Router: 11 API endpoints at `/company-research/*`
- ✅ Migration: Applied (005_company_research)

### UI (Just Added)
- ✅ Navigation: "Company Research" in sidebar
- ✅ List page: `/ui/company-research` - Filter by role, create runs
- ✅ Run detail: `/ui/company-research/runs/{id}` - View/edit prospects
- ✅ Inline editing: Update manual priority, pin status, status
- ✅ Dev helper: Seed dummy prospects button

---

## 🚀 How to Test (Step-by-Step for Non-Technical Users)

### Prerequisites

1. **Start the server**:
   ```bash
   cd C:\ATS
   C:/ATS/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

2. **Open browser** to: `http://127.0.0.1:8000`

3. **Login** with your admin credentials

---

### Test Flow

#### 1. Navigate to Company Research

1. After logging in, you'll see the sidebar navigation
2. Click **"Company Research"** (near the bottom, above Settings)
3. You should see the Company Research main page

**Expected**:
- Page title: "Company Research"
- Description text about managing discovery runs
- Dropdown: "Select Role/Mandate"

---

#### 2. Select a Role

1. Click the **"Select Role/Mandate"** dropdown
2. Choose any role (e.g., "CEO" at a company)
3. The page will reload and show:
   - Selected role info (title and company name)
   - Button: "+ New Company Research Run"
   - Table: "Research Runs" (empty if first time)

---

#### 3. Create a Research Run

1. Click **"+ New Company Research Run"**
2. A modal appears with a form
3. Fill in:
   - **Run Name**: `Top 50 NBFCs in India 2024`
   - **Description**: `Identify leading NBFCs by total assets`
   - **Sector**: `nbfc`
   - **Region Scope**: `IN`
   - **Primary Metric**: `Total Assets` (default)
   - **Currency**: `USD` (default)
   - **As-of Year**: `2024` (default)
   - **Direction**: `Highest first` (default)
4. Click **"Create Run"**

**Expected**:
- Redirects to the run detail page
- Shows run info (name, description, status, ranking metric)
- Table: "Company Prospects (0)" (empty initially)

---

#### 4. Create Dummy Prospects (Dev Testing)

Since we don't have agents yet, use the dev helper:

1. On the run detail page, click **"🔧 Create Dummy Prospects (Dev Only)"** button (top right)
2. Page reloads

**Expected**:
- Green success message: "Created 5 dummy prospects"
- Table now shows **5 companies**:
  1. ABC Financial Services Ltd
  2. XYZ Capital & Investments
  3. Premier Finance Corporation
  4. Strategic NBFC Holdings (has a 📌 pin)
  5. Omega Credit Solutions

**Note**: This button is only visible to admin users and is for testing only.

---

#### 5. Test Manual Ordering

1. At the top of the page, check the **"Sort by"** dropdown
2. It should be set to **"My Manual Order"** by default

**Expected Order** (pinned first, then by manual priority):
1. 📌 Strategic NBFC Holdings (pinned, priority=1)
2. Premier Finance (priority=2)
3. XYZ Capital (priority=3)
4. ABC Financial (no priority, fallback to AI score 0.92)
5. Omega Credit (no priority, fallback to AI score 0.65)

**Key Observations**:
- Row with 📌 has yellow background
- "My Rank" column shows: 1, 2, 3, blank, blank
- AI Relevance scores shown as badges (green for high, orange for medium)

---

#### 6. Test AI Ordering

1. Change **"Sort by"** dropdown to **"AI Relevance"**
2. Page reloads

**Expected Order** (pinned first, then by relevance score):
1. 📌 Strategic NBFC Holdings (pinned, AI=0.71)
2. ABC Financial (AI=0.92) ← Highest relevance!
3. XYZ Capital (AI=0.85)
4. Premier Finance (AI=0.78)
5. Omega Credit (AI=0.65)

**Key Observation**: 
- Pinned items always appear first
- Then sorted purely by AI relevance (highest first)
- Manual priority is ignored in AI order mode

---

#### 7. Test Pinning a Company

Let's promote "ABC Financial" (currently 2nd in AI order):

1. Make sure you're in **"AI Relevance"** order mode
2. Click the **○** (circle) next to "ABC Financial Services"
3. Page reloads

**Expected**:
- Success message appears
- ABC Financial now has a 📌 and yellow background
- Order changes:
  1. 📌 ABC Financial (pinned, AI=0.92)
  2. 📌 Strategic NBFC (pinned, AI=0.71)
  3. XYZ Capital (AI=0.85)
  4. Premier Finance (AI=0.78)
  5. Omega Credit (AI=0.65)

**Key Observation**: 
- Both pinned items at top
- When both pinned, sorted by AI relevance (0.92 > 0.71)

---

#### 8. Test Manual Priority Changes

Let's give ABC Financial a manual rank:

1. Switch back to **"My Manual Order"**
2. Find "ABC Financial Services" row
3. In the **"My Rank"** column, enter: `1`
4. Click **"Save"** button on that row
5. Page reloads

**Expected**:
- Success message appears
- Order now shows:
  1. 📌 ABC Financial (pinned, priority=1)
  2. 📌 Strategic NBFC (pinned, priority=1)
  3. Premier Finance (priority=2)
  4. XYZ Capital (priority=3)
  5. Omega Credit (no priority)

**Key Observation**:
- Both have priority=1 and are pinned
- ABC wins because it has higher AI relevance (0.92 vs 0.71)
- This is the tie-breaking rule

---

#### 9. Test Status Changes

1. Find "ABC Financial Services" row
2. In the **"Status"** dropdown, change from "New" to **"Approved"**
3. Click **"Save"** button
4. Page reloads

**Expected**:
- Status dropdown now shows "Approved" selected
- (In a production version, you might filter by status or show different colors)

---

#### 10. Test Unpinning

1. Click the 📌 next to "Strategic NBFC Holdings"
2. Page reloads

**Expected**:
- Strategic NBFC no longer has 📌 (shows ○ instead)
- No yellow background
- Order changes to:
  1. 📌 ABC Financial (pinned, priority=1) ← Only pinned item
  2. Strategic NBFC (priority=1, but not pinned)
  3. Premier Finance (priority=2)
  4. XYZ Capital (priority=3)
  5. Omega Credit (no priority)

**Key Observation**: Pinned status always trumps manual priority.

---

#### 11. Verify AI Ordering Unaffected

1. Switch to **"AI Relevance"** ordering
2. Check the order

**Expected**:
- Should show purely by AI relevance:
  1. 📌 ABC Financial (pinned, AI=0.92)
  2. XYZ Capital (AI=0.85)
  3. Premier Finance (AI=0.78)
  4. Strategic NBFC (AI=0.71)
  5. Omega Credit (AI=0.65)

**Critical Validation**:
- Manual priority changes did NOT affect AI scores!
- Strategic NBFC still shows relevance=0.71 (unchanged)
- This proves the separation of AI vs manual fields is working

---

## ✅ Success Criteria

You've successfully validated the Company Research module if:

1. ✅ Navigation item appears and links to `/ui/company-research`
2. ✅ Can filter by role/mandate
3. ✅ Can create a new research run with config
4. ✅ Dev helper creates 5 dummy prospects
5. ✅ Manual ordering: Pinned → Priority ASC → Relevance DESC
6. ✅ AI ordering: Pinned → Relevance DESC
7. ✅ Can toggle pin status (click ○ or 📌)
8. ✅ Can set manual priority (1 = highest)
9. ✅ Can change status (new, approved, rejected)
10. ✅ Changes to manual fields don't corrupt AI scores
11. ✅ Yellow background for pinned rows
12. ✅ Success messages after updates

---

## 🎯 What This Proves

**Phase 1 Complete**:
- ✅ Backend structure (models, schemas, repos, services, routes)
- ✅ Database tables (4 tables with proper indexes)
- ✅ API endpoints (11 REST endpoints)
- ✅ UI layer (list, detail, create, inline edit)
- ✅ Dual ordering modes (AI vs Manual)
- ✅ Pin/rank/status management
- ✅ Field separation (AI never touched by manual updates)

**Ready for Phase 2**:
- Agents can now populate company_prospect via POST /company-research/prospects
- Evidence tracking ready: POST /prospects/{id}/evidence
- Metrics tracking ready: POST /prospects/{id}/metrics
- Config-driven ranking ready (primary_metric, currency, etc.)

---

## 🧪 Optional: Test via Swagger (For Technical Validation)

If you want to test the API directly:

1. Open: `http://127.0.0.1:8000/docs`
2. Login via `/auth/login` and authorize with the token
3. Test endpoints:
   - `POST /company-research/runs` - Create run
   - `GET /company-research/runs/{id}/prospects?order_by=ai` - AI order
   - `GET /company-research/runs/{id}/prospects?order_by=manual` - Manual order
   - `PATCH /company-research/prospects/{id}/manual` - Update manual fields

**Note**: The UI is now the primary interface. Swagger is for debugging/testing only.

---

## 📝 Known Limitations (Phase 1)

✅ **What Works**:
- Creating runs manually via UI
- Seeding dummy prospects (dev helper)
- Viewing and sorting prospects
- Manual ranking and pinning
- Inline editing of priority/status

❌ **What's NOT Yet Implemented** (Future Phases):
- Automated company discovery (agents)
- Web scraping for evidence
- Automated metric collection
- Currency conversion (value_usd must be provided manually)
- Deduplication (name_normalized exists but not used)
- Bulk actions (select multiple, approve all)
- Export to CSV/Excel
- Evidence and metrics UI (tables exist, no UI yet)
- Integration with main "Companies" table (conversion workflow)

---

## 🔧 Troubleshooting

### "Company Research" not in sidebar
- Refresh the page (F5)
- Clear browser cache
- Check you're logged in
- Restart the server

### "Create Dummy Prospects" button not visible
- Only visible to admin users
- Check `current_user.role == 'admin'` or `'ADMIN'`

### Changes not saving
- Check for error messages at top of page
- Check terminal for server errors
- Ensure you clicked "Save" button (not just changed the field)

### Ordering looks wrong
- Verify you're looking at the correct "Sort by" mode
- Remember: Pinned ALWAYS appears first
- Manual order: Priority ASC (1=highest, nulls last)
- AI order: Relevance DESC (highest first)

### Server errors
- Check terminal output for stack traces
- Common issues:
  - Invalid UUID format
  - Role not found
  - Permission denied (not admin/consultant)

---

## 🎉 Next Steps

Once you've validated the UI works:

1. **Remove/Hide the dev helper button** before production
2. **Build Phase 2**: Agentic company discovery
   - Web crawlers to find companies
   - LLM-based relevance scoring
   - Automated evidence collection
3. **Add evidence/metrics UI tabs** (show sources, financial data)
4. **Build conversion flow**: "Approved" → Create company in main table
5. **Add bulk actions**: Select multiple, approve/reject all
6. **Add export functionality**: Download prospects as CSV

---

## 📊 Verification Commands (For Developers)

```bash
# Verify migration applied
C:/ATS/.venv/Scripts/python.exe -m alembic current
# Expected: 005_company_research (head)

# Verify tables exist
C:/ATS/.venv/Scripts/python.exe scripts/verify_company_research_tables.py
# Expected: ✅ All 4 tables created

# Check API routes loaded
C:/ATS/.venv/Scripts/python.exe -c "from app.routers import company_research; print(f'API routes: {len(company_research.router.routes)}')"
# Expected: API routes: 11

# Check UI routes loaded  
C:/ATS/.venv/Scripts/python.exe -c "from app.ui.routes import company_research; print(f'UI routes: {len(company_research.router.routes)}')"
# Expected: UI routes: 5

# Start server
C:/ATS/.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

---

**Status**: ✅ **Phase 1 Complete - Ready for User Testing!**

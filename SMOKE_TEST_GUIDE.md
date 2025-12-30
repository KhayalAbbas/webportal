# Company Research Module - Smoke Test Guide

## Prerequisites

✅ Migration applied: `alembic upgrade head`
✅ Server running: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
✅ Browser open to: `http://127.0.0.1:8000/docs` (Swagger UI)

## Authentication Setup

Before testing the endpoints, you need to authenticate:

### Step 1: Login via Swagger UI

1. **Find the `/auth/login` endpoint** in Swagger UI (under "Authentication" section)
2. **Click "Try it out"**
3. **Set the `X-Tenant-ID` header**: Click "Add string item" and enter your tenant ID
   - If you don't know your tenant ID, use: `00000000-0000-0000-0000-000000000000` (or check your database)
4. **Enter credentials** in the request body:
   ```json
   {
     "email": "admin@example.com",
     "password": "admin123"
   }
   ```
   (Or use your actual admin credentials)

5. **Click "Execute"**
6. **Copy the `access_token`** from the response
7. **Click the "Authorize" button** at the top of the Swagger page (or the padlock icon)
8. **Paste the token** in the "Value" field with format: `Bearer YOUR_TOKEN_HERE`
9. **Click "Authorize"** and then "Close"

You're now authenticated! All subsequent requests will include your JWT token.

---

## Test Flow

### Test 1: Create a Research Run

**Endpoint**: `POST /company-research/runs`

1. **Expand** the endpoint
2. **Click "Try it out"**
3. **Paste this request body**:
   ```json
   {
     "role_mandate_id": "45a00716-0fec-4de7-9ccf-26f14eb5f5fb",
     "name": "Top NBFCs in India 2024",
     "description": "Research exercise to identify top 50 NBFCs by total assets",
     "status": "active",
     "config": {
       "ranking": {
         "primary_metric": "total_assets",
         "currency": "USD",
         "as_of_year": 2024,
         "direction": "desc"
       },
       "enrichment": {
         "metrics_to_collect": ["total_assets", "revenue", "employees"]
       }
     }
   }
   ```

   **Note**: If you get a 404 error about `role_mandate_id`, run this command first to get a valid role ID:
   ```bash
   python scripts/get_sample_role.py
   ```
   Then replace the `role_mandate_id` value above.

4. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Response body shows created run with an `id` field
- **COPY THE `id` VALUE** - you'll need it for the next steps!

Example response:
```json
{
  "id": "abc12345-...",
  "tenant_id": "...",
  "role_mandate_id": "45a00716-...",
  "name": "Top NBFCs in India 2024",
  "status": "active",
  ...
}
```

---

### Test 2: Seed Dummy Prospects

**Endpoint**: `POST /company-research/runs/{run_id}/seed-dummy-prospects`

1. **Expand** the endpoint (it's at the bottom under "DEV/TEST ENDPOINTS")
2. **Click "Try it out"**
3. **Paste the run ID** from Test 1 into the `run_id` parameter field
4. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Response shows **5 company prospects** created:
  1. ABC Financial Services Ltd (relevance: 0.92, no manual priority)
  2. XYZ Capital & Investments (relevance: 0.85, manual priority: 3)
  3. Premier Finance Corporation (relevance: 0.78, manual priority: 2)
  4. Strategic NBFC Holdings (relevance: 0.71, manual priority: 1, **pinned**)
  5. Omega Credit Solutions (relevance: 0.65, no manual priority)

**Copy one of the prospect IDs** - you'll need it for Test 5.

---

### Test 3: List Prospects (AI Ordering)

**Endpoint**: `GET /company-research/runs/{run_id}/prospects`

1. **Expand** the endpoint
2. **Click "Try it out"**
3. **Enter parameters**:
   - `run_id`: Paste the run ID from Test 1
   - `order_by`: Enter `ai`
   - Leave other fields empty/default
4. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Prospects ordered by **AI relevance**:
  1. **Strategic NBFC Holdings** (pinned=true, relevance=0.71)  ← Pinned first!
  2. **ABC Financial Services** (relevance=0.92)
  3. **XYZ Capital** (relevance=0.85)
  4. **Premier Finance** (relevance=0.78)
  5. **Omega Credit** (relevance=0.65)

**Key Observation**: Pinned items appear first, then sorted by `relevance_score` DESC.

---

### Test 4: List Prospects (Manual Ordering)

**Endpoint**: `GET /company-research/runs/{run_id}/prospects` (same as Test 3)

1. **Keep the same endpoint expanded**
2. **Change the `order_by` parameter** to `manual`
3. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Prospects ordered by **manual priority**:
  1. **Strategic NBFC Holdings** (pinned=true, manual_priority=1)  ← Pinned + Priority 1
  2. **Premier Finance** (manual_priority=2)
  3. **XYZ Capital** (manual_priority=3)
  4. **ABC Financial Services** (manual_priority=null, relevance=0.92)  ← Nulls last, then by relevance
  5. **Omega Credit** (manual_priority=null, relevance=0.65)

**Key Observation**: 
- Pinned first
- Then by `manual_priority` ASC (1 = highest)
- NULL priorities go last, sorted by relevance

---

### Test 5: Update Manual Fields

**Endpoint**: `PATCH /company-research/prospects/{prospect_id}/manual`

Let's promote "ABC Financial Services" (currently 4th in manual order) to the top:

1. **Expand** the endpoint
2. **Click "Try it out"**
3. **Paste the prospect ID** for "ABC Financial Services" (from Test 2 response)
4. **Paste this request body**:
   ```json
   {
     "manual_priority": 1,
     "manual_notes": "Key strategic NBFC - prefer to keep at top position",
     "is_pinned": true,
     "status": "approved"
   }
   ```
5. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Response shows updated prospect with:
  - `manual_priority`: 1
  - `manual_notes`: "Key strategic NBFC..."
  - `is_pinned`: true
  - `status`: "approved"
  - **AI fields unchanged**: `relevance_score` still 0.92, `evidence_score` still 0.88

---

### Test 6: Verify Manual Override Worked

**Endpoint**: `GET /company-research/runs/{run_id}/prospects` (with `order_by=manual`)

1. **Go back** to the prospects listing endpoint from Test 4
2. **Make sure `order_by` is set to `manual`**
3. **Click "Execute"** again

**Expected Result**:
- Status code: `200 OK`
- New ordering:
  1. **ABC Financial Services** (pinned=true, manual_priority=1)  ← Now at top!
  2. **Strategic NBFC Holdings** (pinned=true, manual_priority=1)  ← Also priority 1
  3. **Premier Finance** (manual_priority=2)
  4. **XYZ Capital** (manual_priority=3)
  5. **Omega Credit** (manual_priority=null)

**Key Observation**: 
- ABC Financial is now pinned and has priority=1
- Both pinned items appear first
- When priorities are equal, they're sorted by relevance (ABC has 0.92 vs Strategic has 0.71)

---

### Test 7: Verify AI Ordering Unchanged

**Endpoint**: `GET /company-research/runs/{run_id}/prospects` (with `order_by=ai`)

1. **Change `order_by` back to `ai`**
2. **Click "Execute"**

**Expected Result**:
- Status code: `200 OK`
- Ordering (pinned first, then relevance):
  1. **ABC Financial Services** (pinned=true, relevance=0.92)  ← Now pinned!
  2. **Strategic NBFC Holdings** (pinned=true, relevance=0.71)
  3. **XYZ Capital** (relevance=0.85)
  4. **Premier Finance** (relevance=0.78)
  5. **Omega Credit** (relevance=0.65)

**Key Observation**: AI ordering only cares about pinned status and relevance score, not manual_priority.

---

## Success Criteria

✅ **All tests passed if**:
1. Research run created successfully
2. 5 dummy prospects created
3. AI ordering shows prospects by relevance (highest first)
4. Manual ordering shows prospects by manual_priority (1 = highest)
5. NULL priorities appear last in manual ordering
6. Manual update endpoint successfully changed priority and pinned status
7. AI fields (relevance_score, evidence_score) were NOT changed by manual update
8. Both ordering modes respect `is_pinned` (pinned items always first)

---

## Troubleshooting

### "401 Unauthorized" errors
- Make sure you've logged in via `/auth/login`
- Copy the access token and click "Authorize" button at top
- Enter token as: `Bearer YOUR_TOKEN_HERE`

### "404 Not Found" for role_mandate_id
- Run: `python scripts/get_sample_role.py`
- Use the role ID it prints in your request body

### "403 Forbidden" errors
- Make sure you're logged in as an admin or consultant user
- Check that X-Tenant-ID header matches your user's tenant

### Server not running
- Start with: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
- Or: `python -m uvicorn app.main:app --reload`
- Access docs at: `http://127.0.0.1:8000/docs`

---

## Cleanup (Optional)

To remove test data and start fresh:

```sql
DELETE FROM company_prospect WHERE company_research_run_id IN (
  SELECT id FROM company_research_run WHERE name LIKE '%NBFC%'
);
DELETE FROM company_research_run WHERE name LIKE '%NBFC%';
```

Or just create a new research run for the next test.

---

## Next Steps

After confirming basic functionality:
1. Test evidence endpoints: `POST/GET /prospects/{id}/evidence`
2. Test metrics endpoints: `POST/GET /prospects/{id}/metrics`
3. Test filtering: `GET /prospects?status=approved&min_relevance_score=0.8`
4. Remove/protect the `/seed-dummy-prospects` endpoint before production
5. Implement Phase 2: AI orchestration and automated discovery

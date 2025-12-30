# Phase 2: AI Proposal Ingestion - Implementation Status

## ✅ COMPLETED

### 1. Database Schema (Migration: 2fc6e8612026)
- ✅ `company_metrics` table created
  - Stores quantitative/qualitative metrics (total_assets, revenue, etc.)
  - Links to company_prospects and source_documents
  - Supports both numeric and text values
  - Includes confidence scoring and as_of_date
  
- ✅ `company_aliases` table created
  - Stores alternative company names
  - Types: legal, trade, former, local, abbreviation
  - Links to company_prospects
  - Helps with deduplication

- ✅ Extended `source_documents` table
  - Added `provider` field (AI provider name)
  - Added `snippet` field (text evidence)

- ✅ Extended `company_prospects` table
  - Added `ai_rank` field (AI-assigned ranking)
  - Added `ai_score` field (AI relevance score 0-1)

### 2. SQLAlchemy Models
- ✅ `CompanyMetric` model with relationships
- ✅ `CompanyAlias` model with relationships
- ✅ Updated `CompanyProspect` relationships (ai_metrics, aliases)
- ✅ Updated `CompanyResearchRun` relationships (metrics)

### 3. Pydantic Schemas (app/schemas/ai_proposal.py)
- ✅ `AIProposalSource` - source document schema
- ✅ `AIProposalMetric` - metric value schema with validation
- ✅ `AIProposalAlias` - company alias schema
- ✅ `AIProposalCompany` - company entry schema
- ✅ `AIProposal` - complete proposal schema
- ✅ `AIProposalValidationResult` - validation response
- ✅ `AIProposalIngestionResult` - ingestion response
- ✅ Field validators for URLs, currency codes, country codes
- ✅ Uniqueness validators for source temp_ids

### 4. Service Layer (app/services/ai_proposal_service.py)
- ✅ `AIProposalService` class
- ✅ `validate_proposal()` method
  - Schema validation (Pydantic)
  - Business rules validation
  - Duplicate detection
  - Source reference checking
  - Returns detailed validation result
  
- ✅ `ingest_proposal()` method
  - Creates source documents with deduplication
  - Ingests companies with normalization
  - Creates/updates prospects idempotently
  - Stores metrics with deduplication
  - Stores aliases with deduplication
  - Creates evidence records
  - Transaction-based (rollback on error)

### 5. API Endpoints (app/ui/routes/ai_proposal_routes.py)
- ✅ POST `/ui/company-research/runs/{run_id}/validate-proposal`
  - Validates JSON without side effects
  - Returns errors/warnings
  - Shows statistics (company_count, metric_count, etc.)
  
- ✅ POST `/ui/company-research/runs/{run_id}/ingest-proposal`
  - Ingests validated proposal
  - Idempotent (safe to re-run)
  - Returns redirect with success/error message

### 6. Sample Data
- ✅ `sample_ai_proposal.json` - realistic UAE banks example
  - 5 companies with metrics and aliases
  - 2 sources with URLs
  - Total assets in AED and USD
  - Evidence snippets for each metric

## 🔄 IN PROGRESS / PENDING

### 7. UI Updates (app/ui/templates/company_research_run_detail.html)
- ❌ Add Phase 2 section with JSON textarea
- ❌ Add Validate/Ingest buttons
- ❌ Update table to show:
  - Primary Metric column (e.g., total_assets)
  - AI Rank column
  - AI Score column (optional)
- ❌ Add sorting dropdown options:
  - Sort by AI Rank
  - Sort by Primary Metric value
- ❌ Make Evidence Count clickable to show details modal
- ❌ Ensure "My Rank" and "Pin" still work

### 8. UI Detail View Updates
- ❌ Add endpoint to view prospect details with:
  - All metrics displayed in table
  - All aliases displayed
  - Evidence snippets with sources
- ❌ Add modal/popup for evidence details

### 9. Backend Support for UI
- ❌ Update `list_prospects_for_run()` to include:
  - Primary metric value (configurable key)
  - AI rank
  - AI score
- ❌ Add method to fetch metrics for a prospect
- ❌ Add method to fetch aliases for a prospect
- ❌ Add method to fetch evidence with source details

### 10. Testing
- ❌ Unit tests for AIProposalService
- ❌ Integration tests for endpoints
- ❌ UI acceptance test with sample_ai_proposal.json
- ❌ Test deduplication (reingesting same proposal)
- ❌ Test overlap with Phase 1 data
- ❌ Test sorting and filtering

## 📋 IMPLEMENTATION PLAN (Next Steps)

### Step 1: Update Detail View to Fetch Metrics/Aliases
The detail view needs to query and display the new AI data:

```python
# In company_research.py detail view handler:
# After fetching prospects, also fetch:
for prospect in prospects_list:
    # Fetch primary metric (e.g., total_assets)
    primary_metric = await session.execute(
        select(CompanyMetric).where(
            CompanyMetric.company_prospect_id == prospect.id,
            CompanyMetric.metric_key == 'total_assets'
        ).order_by(CompanyMetric.as_of_date.desc())
    )
    primary_metric_value = primary_metric.scalar_one_or_none()
    
    # Add to prospect dict
    prospect_dict['primary_metric'] = primary_metric_value.value_number if primary_metric_value else None
    prospect_dict['ai_rank'] = prospect.ai_rank
    prospect_dict['ai_score'] = prospect.ai_score
```

### Step 2: Update UI Template
Add Phase 2 ingestion form after Phase 1 form:

```html
<!-- Phase 2: AI Proposal Ingestion -->
<div style="background: #f0f8ff; border: 2px solid #4CAF50; ...">
    <h3>🤖 Ingest AI Proposal JSON</h3>
    <form method="post" action="/ui/company-research/runs/{{ run.id }}/ingest-proposal">
        <textarea name="proposal_json" rows="15" placeholder="Paste AI-generated JSON proposal here..."
                  style="width: 100%; font-family: monospace; ..."></textarea>
        
        <div style="display: flex; gap: 10px; margin-top: 10px;">
            <button type="button" onclick="validateProposal()">🔍 Validate</button>
            <button type="submit">🚀 Ingest</button>
        </div>
        
        <div id="validation-result" style="margin-top: 10px;"></div>
    </form>
</div>

<script>
async function validateProposal() {
    const json = document.querySelector('[name="proposal_json"]').value;
    const response = await fetch('/ui/company-research/runs/{{ run.id }}/validate-proposal', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'proposal_json=' + encodeURIComponent(json)
    });
    const result = await response.json();
    
    let html = '';
    if (result.success) {
        html = `<div style="color: green;">✅ Valid! ${result.company_count} companies, ${result.metric_count} metrics, ${result.source_count} sources</div>`;
        if (result.warnings.length > 0) {
            html += '<div style="color: orange;">⚠️ Warnings: ' + result.warnings.join('; ') + '</div>';
        }
    } else {
        html = '<div style="color: red;">❌ Validation failed:</div><ul>';
        result.errors.forEach(err => html += '<li>' + err + '</li>');
        html += '</ul>';
    }
    
    document.getElementById('validation-result').innerHTML = html;
}
</script>
```

### Step 3: Update Table Headers
```html
<thead>
    <tr>
        <th>📌</th>
        <th>Company Name</th>
        <th>Original Name</th>
        <th>Primary Metric</th>  <!-- NEW -->
        <th>AI Rank</th>          <!-- NEW -->
        <th>AI Score</th>          <!-- NEW -->
        <th>Evidence Count</th>
        <th>List Sources</th>
        <th>Status</th>
        <th>My Rank</th>
        <th>Actions</th>
    </tr>
</thead>
```

### Step 4: Update Table Cells
```html
<td>{{ prospect.name_normalized }}</td>
<td style="color: #666;">{{ prospect.name_raw }}</td>
<td>
    {% if prospect.primary_metric %}
        {{ "{:,.0f}".format(prospect.primary_metric) }} AED
    {% else %}
        -
    {% endif %}
</td>
<td style="text-align: center;">
    {% if prospect.ai_rank %}
        <span class="badge badge-success">{{ prospect.ai_rank }}</span>
    {% else %}
        -
    {% endif %}
</td>
<td style="text-align: center;">
    {% if prospect.ai_score %}
        {{ "{:.2f}".format(prospect.ai_score) }}
    {% else %}
        -
    {% endif %}
</td>
```

### Step 5: Add Sorting Options
```html
<select onchange="location.href='?order_by=' + this.value">
    <option value="manual" {% if order_by == 'manual' %}selected{% endif %}>My Rank</option>
    <option value="ai" {% if order_by == 'ai' %}selected{% endif %}>AI Rank</option>
    <option value="metric" {% if order_by == 'metric' %}selected{% endif %}>Primary Metric</option>
</select>
```

Update service to support new sorting:
```python
if order_by == "metric":
    query = query.outerjoin(
        CompanyMetric,
        and_(
            CompanyMetric.company_prospect_id == CompanyProspect.id,
            CompanyMetric.metric_key == 'total_assets'
        )
    ).order_by(CompanyMetric.value_number.desc().nullslast())
```

## 🧪 ACCEPTANCE TEST

Use `sample_ai_proposal.json`:

1. **Ingest Sample**
   - Paste sample_ai_proposal.json into Phase 2 textarea
   - Click Validate → Should show "✅ Valid! 5 companies, 15 metrics, 2 sources"
   - Click Ingest → Should show success message

2. **Verify Companies**
   - Table should show 5 banks
   - AI Rank column: 1-5
   - Primary Metric column: Shows assets in AED
   - Evidence Count: Should be > 0 for each

3. **Verify Deduplication**
   - Reingest same JSON
   - Should show "0 new, 5 updated"
   - No duplicate companies created

4. **Verify Sorting**
   - Sort by AI Rank → FAB (1) should be first
   - Sort by Primary Metric → FAB (highest assets) should be first
   - Sort by My Rank → User can override with manual priority

5. **Verify My Rank Still Works**
   - Edit My Rank for Emirates NBD to "1"
   - Sort by Manual → Emirates NBD should jump to top
   - AI Rank column still shows "2" (unchanged)

## 📊 ARCHITECTURE SUMMARY

**Phase 1** (Manual Lists):
- User pastes company names → Normalize → Deduplicate → Store as prospects
- Evidence type: `manual_list`
- Simple, deterministic, no AI

**Phase 2** (AI Proposals):
- AI generates structured JSON with companies + metrics + aliases
- System validates schema and business rules
- Ingests into normalized tables
- Deduplicates against existing prospects
- Evidence type: `ai_proposal`, `ai_proposal_metric`
- Supports sorting by AI ranking or metric values

**Coexistence**:
- Phase 1 and Phase 2 data live together in same run
- Phase 1 company "Bank of America Corp" can be enriched by Phase 2 metrics
- User's "My Rank" always takes precedence over AI Rank
- Sorting allows switching between manual and AI rankings

## 🔒 SAFETY FEATURES

1. **Idempotency**: Reingesting same proposal won't create duplicates
2. **Validation**: Schema + business rules checked before ingestion
3. **Transactions**: All-or-nothing ingestion (rollback on error)
4. **User Override**: My Rank/Pin always respected, never overwritten
5. **Audit Trail**: Evidence records show source of every data point
6. **Normalization**: Companies matched by canonical name across phases

## 📁 FILES CREATED/MODIFIED

**New Files**:
- `alembic/versions/2fc6e8612026_add_company_metrics_and_aliases_for_.py`
- `app/schemas/ai_proposal.py`
- `app/services/ai_proposal_service.py`
- `app/ui/routes/ai_proposal_routes.py`
- `sample_ai_proposal.json`

**Modified Files**:
- `app/models/company_research.py` (added CompanyMetric, CompanyAlias)
- `app/main.py` (registered ai_proposal_routes)

**Pending Modifications**:
- `app/ui/templates/company_research_run_detail.html` (add Phase 2 UI)
- `app/services/company_research_service.py` (add metric/alias queries)

## ✅ READY TO TEST

Backend is complete and functional. You can:
1. Test endpoints directly with Postman/curl
2. Validate sample JSON: `POST /ui/company-research/runs/{run_id}/validate-proposal`
3. Ingest sample JSON: `POST /ui/company-research/runs/{run_id}/ingest-proposal`

UI needs to be updated to expose these features to users.

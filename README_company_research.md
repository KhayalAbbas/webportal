# Company Discovery / Agentic Sourcing Engine - Phase 1

## Overview

This module provides the **backend infrastructure** for the Company Discovery / Agentic Sourcing Engine. Phase 1 focuses on database structures, API endpoints, and manual ranking workflows. External AI orchestration (web crawling, LLM scoring, automated enrichment) will come in later phases.

## Purpose

The Company Discovery module helps researchers identify, rank, and manage potential target companies for specific mandates/roles. It supports:

1. **AI-Calculated Scoring**: Relevance and evidence scores computed by future AI systems
2. **Manual Ranking**: User-defined priority rankings and notes that override AI suggestions
3. **Evidence Tracking**: Sources and citations for why a company is relevant
4. **Metric Collection**: Financial and operational data with currency conversion

## Database Schema

### 1. `company_research_run`

Discovery exercises tied to specific role mandates.

**Key Fields**:
- `role_mandate_id`: The role/mandate this research is for
- `name`: Human-readable name (e.g., "Top Asset Managers in DACH Region")
- `status`: `active`, `completed`, `archived`
- `config`: JSONB configuration for ranking and enrichment

**Config Structure**:
```json
{
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
```

**Indexes**:
- `role_mandate_id`, `status`

---

### 2. `company_prospect`

Potential companies discovered during research runs.

**Key Fields**:
- `company_research_run_id`: Parent research run
- `name`, `name_normalized`: Company name (normalized for deduplication)
- `website`, `linkedin_url`: Online presence
- `headquarters_location`, `country_code`: Geographic data
- `industry_sector`, `brief_description`: Classification

**AI Fields** (never touched by manual updates):
- `relevance_score`: 0.0 - 1.0 (AI-calculated match quality)
- `evidence_score`: 0.0 - 1.0 (strength of evidence)

**Manual Override Fields** (ONLY updated via manual endpoint):
- `manual_priority`: 1 = highest priority (integer ranking)
- `manual_notes`: User comments
- `is_pinned`: Pin to top of lists

**Workflow Fields**:
- `status`: `new`, `approved`, `rejected`, `duplicate`, `converted`
- `converted_to_company_id`: Link to created company record

**Indexes**:
- `company_research_run_id`, `status`, `name_normalized`
- `relevance_score`, `manual_priority`, `is_pinned`

---

### 3. `company_prospect_evidence`

Evidence sources explaining why a company is relevant.

**Key Fields**:
- `company_prospect_id`: Parent prospect
- `source_type`: `ranking_list`, `association_directory`, `regulatory_register`, `web_crawl`, `manual_entry`
- `source_name`: Human-readable source name
- `source_url`: Link to source
- `evidence_snippet`: Excerpt or quote
- `evidence_weight`: 0.0 - 1.0 (credibility/importance)
- `metadata`: Additional structured data

**Indexes**:
- `company_prospect_id`, `source_type`

---

### 4. `company_prospect_metric`

Numeric metrics with currency conversion.

**Key Fields**:
- `company_prospect_id`: Parent prospect
- `metric_type`: `total_assets`, `revenue`, `employees`, `net_income`, `market_cap`, `equity`, `debt`
- `value_raw`: Original value in source currency
- `currency`: Source currency code (USD, EUR, GBP, etc.)
- `value_usd`: Converted value in USD (for standardized ranking)
- `as_of_year`: Data vintage (2024, 2023, etc.)
- `source`: Where this metric came from
- `metadata`: Additional details

**Indexes**:
- `company_prospect_id`, `metric_type`
- Composite: `metric_type + as_of_year` (for time-series queries)

---

## Relationships

```
company_research_run (1) → (N) company_prospect
company_prospect (1) → (N) company_prospect_evidence
company_prospect (1) → (N) company_prospect_metric

company_research_run → role (FK: role_mandate_id)
company_research_run → user (FK: created_by_user_id)
company_prospect → company (FK: converted_to_company_id, optional)
```

All relationships use `CASCADE` delete for child records, except nullable FKs which use `SET NULL`.

---

## API Endpoints

### Research Run Endpoints

#### `POST /company-research/runs`
Create a new research run for a mandate.

**Request Body**:
```json
{
  "role_mandate_id": "uuid",
  "name": "Top Private Equity Firms in UK",
  "description": "Searching for firms managing £500M+ in private equity",
  "status": "active",
  "config": {
    "ranking": {
      "primary_metric": "total_assets",
      "currency": "GBP",
      "as_of_year": 2024,
      "direction": "desc"
    }
  }
}
```

**Response**: `CompanyResearchRunRead`

---

#### `GET /company-research/runs/{run_id}`
Get research run with prospect count summary.

**Response**: `CompanyResearchRunSummary` (includes `prospect_count`)

---

#### `GET /company-research/runs/{run_id}/prospects`
List prospects for a run with filtering and ordering.

**Query Parameters**:
- `status`: Filter by status (`new`, `approved`, etc.)
- `min_relevance_score`: Minimum AI relevance (0.0 - 1.0)
- `order_by`: `ai` (default, by relevance_score) or `manual` (by manual_priority)
- `limit`: Max results (default 50, max 200)
- `offset`: Pagination offset

**Ordering Logic**:
- **AI mode**: `is_pinned DESC`, `relevance_score DESC`, `evidence_score DESC`
- **Manual mode**: `is_pinned DESC`, `manual_priority ASC NULLS LAST`, `relevance_score DESC`

**Response**: `List[CompanyProspectListItem]`

---

#### `PATCH /company-research/runs/{run_id}`
Update run status, description, or config.

**Request Body**: `CompanyResearchRunUpdate`

---

### Company Prospect Endpoints

#### `POST /company-research/prospects`
Create a new prospect (typically called by AI/system).

**Request Body**: `CompanyProspectCreate`

---

#### `GET /company-research/prospects/{prospect_id}`
Get full prospect details.

**Response**: `CompanyProspectRead`

---

#### `PATCH /company-research/prospects/{prospect_id}/manual`
**CRITICAL**: Update manual override fields ONLY.

This endpoint ensures AI scores are NEVER touched by user input. Only updates:
- `manual_priority`
- `manual_notes`
- `is_pinned`
- `status`

**Request Body**: `CompanyProspectUpdateManual`

---

### Evidence Endpoints

#### `POST /company-research/prospects/{prospect_id}/evidence`
Add evidence to a prospect.

**Request Body**:
```json
{
  "source_type": "ranking_list",
  "source_name": "Top 100 Asset Managers 2024",
  "source_url": "https://example.com/rankings/2024",
  "evidence_snippet": "Ranked #12 in EMEA region",
  "evidence_weight": 0.9
}
```

---

#### `GET /company-research/prospects/{prospect_id}/evidence`
List all evidence for a prospect.

**Response**: `List[CompanyProspectEvidenceRead]`

---

### Metric Endpoints

#### `POST /company-research/prospects/{prospect_id}/metrics`
Add a metric to a prospect.

**Request Body**:
```json
{
  "metric_type": "total_assets",
  "value_raw": 2500000000,
  "currency": "EUR",
  "value_usd": 2750000000,
  "as_of_year": 2024,
  "source": "Company annual report"
}
```

---

#### `GET /company-research/prospects/{prospect_id}/metrics`
List all metrics for a prospect.

**Query Parameters**:
- `metric_type`: Optional filter (e.g., `total_assets`)

**Response**: `List[CompanyProspectMetricRead]`

---

## AI vs. Manual Field Separation

**CRITICAL DESIGN PRINCIPLE**: AI and manual fields are strictly separated to prevent accidental overwrites.

### AI Fields (System Only)
These fields are **ONLY** updated by AI/system processes:
- `relevance_score`
- `evidence_score`

### Manual Fields (User Only)
These fields are **ONLY** updated via the manual endpoint (`PATCH /prospects/{id}/manual`):
- `manual_priority`
- `manual_notes`
- `is_pinned`
- `status` (when user changes it)

**Why This Matters**:
- AI rescoring should never erase user rankings
- User edits should never corrupt AI calculations
- Both systems can coexist and be combined in UI sorting

---

## Typical Workflow

### 1. Create Research Run
```python
POST /company-research/runs
{
  "role_mandate_id": "...",
  "name": "Top 50 FinTech Companies in Germany",
  "config": {
    "ranking": {"primary_metric": "revenue", "direction": "desc"}
  }
}
```

### 2. Add Prospects (via AI/system)
```python
POST /company-research/prospects
{
  "company_research_run_id": "...",
  "name": "Example FinTech GmbH",
  "relevance_score": 0.85,
  "evidence_score": 0.72
}
```

### 3. Add Evidence
```python
POST /company-research/prospects/{id}/evidence
{
  "source_type": "ranking_list",
  "source_name": "Top 100 FinTech DACH 2024",
  "evidence_weight": 0.9
}
```

### 4. Add Metrics
```python
POST /company-research/prospects/{id}/metrics
{
  "metric_type": "revenue",
  "value_raw": 45000000,
  "currency": "EUR",
  "value_usd": 49500000,
  "as_of_year": 2023
}
```

### 5. User Reviews and Ranks
```python
PATCH /company-research/prospects/{id}/manual
{
  "manual_priority": 1,
  "is_pinned": true,
  "manual_notes": "Perfect fit - already have warm intro",
  "status": "approved"
}
```

### 6. Convert to Company
When approved, update:
```python
PATCH /company-research/prospects/{id}/manual
{
  "status": "converted",
  "converted_to_company_id": "..."  # ID of created company record
}
```

---

## Phase 1 Scope

**What's Included**:
- ✅ 4 database tables with proper indexes
- ✅ Repository layer with ordering logic
- ✅ Service layer with validation
- ✅ 12 REST API endpoints
- ✅ Separation of AI vs. manual fields
- ✅ Evidence and metric tracking
- ✅ Currency conversion support (value_usd field)
- ✅ Alembic migration

**What's NOT Included (Future Phases)**:
- ❌ External AI orchestration (web crawling, LLM scoring)
- ❌ Automated company discovery from web sources
- ❌ Real-time enrichment via external APIs
- ❌ Automatic currency conversion (value_usd must be provided)
- ❌ Deduplication logic (name_normalized field exists but not used yet)

---

## Configuration Examples

### Ranking by Total Assets (Descending)
```json
{
  "ranking": {
    "primary_metric": "total_assets",
    "currency": "USD",
    "as_of_year": 2024,
    "direction": "desc"
  }
}
```

### Ranking by Employee Count (Ascending - smallest firms first)
```json
{
  "ranking": {
    "primary_metric": "employees",
    "as_of_year": 2024,
    "direction": "asc"
  }
}
```

### Enrichment Configuration
```json
{
  "enrichment": {
    "metrics_to_collect": [
      "total_assets",
      "revenue",
      "employees",
      "net_income"
    ]
  }
}
```

---

## Files Created

1. **Models**: `app/models/company_research.py` (4 SQLAlchemy models)
2. **Schemas**: `app/schemas/company_research.py` (Pydantic schemas)
3. **Repository**: `app/repositories/company_research_repo.py` (async CRUD)
4. **Service**: `app/services/company_research_service.py` (business logic)
5. **Router**: `app/routers/company_research.py` (FastAPI endpoints)
6. **Migration**: `alembic/versions/005_company_research.py` (Alembic)
7. **Documentation**: `README_company_research.md` (this file)

---

## Next Steps (Future Phases)

1. **Phase 2 - AI Orchestration**: Build agents to discover companies from web sources
2. **Phase 3 - Automated Scoring**: Implement LLM-based relevance scoring
3. **Phase 4 - Real-time Enrichment**: Integrate with external data APIs (Clearbit, LinkedIn, etc.)
4. **Phase 5 - Deduplication**: Fuzzy matching on company names
5. **Phase 6 - Currency Conversion**: Automatic USD conversion via exchange rate API
6. **Phase 7 - UI Components**: Build frontend for research runs and prospect management

---

## Support

For questions about this module:
- Check the inline documentation in source files
- Review API schemas in `app/schemas/company_research.py`
- Test endpoints via `/docs` (FastAPI Swagger UI)

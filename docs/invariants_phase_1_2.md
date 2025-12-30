# Phase 1 & Phase 2 Invariants (Non-Negotiables)

**Last Updated**: 2025-12-26  
**Applies To**: Phase 1 (Manual List Ingestion), Phase 2 (AI Proposal Ingestion)

---

## 1. Scope Boundaries (What Phase 1/2 Do NOT Do)

- ❌ **NO web scraping** - Phase 1/2 are deterministic ingestion only
- ❌ **NO external API calls** during ingestion (validation or ingest endpoints)
- ❌ **NO LLM/AI calls** - Phase 2 ingests pre-generated AI proposals, does not generate them
- ❌ **NO enrichment** - Company data comes only from user input (Phase 1) or AI proposal JSON (Phase 2)
- ❌ **NO heavy work in request thread** - Ingestion is currently synchronous but MUST be movable to background workers without semantic changes
- ✅ Phase 1: Paste company names → normalize → dedupe → create prospects
- ✅ Phase 2: Paste AI-generated JSON → validate schema → ingest companies/metrics/sources

---

## 2. Data Integrity Invariants

### Company vs CompanyProspect
**CRITICAL DISTINCTION**: The system maintains two separate entities:
- **Company** (global, future): Canonical company identity shared across all runs in a tenant. Identified by `(tenant_id, name_normalized)`.
- **CompanyProspect** (run-scoped, current): A company's appearance in a specific research run. Identified by `(tenant_id, run_id, company_id)` or equivalently `(tenant_id, run_id, name_normalized)` for deduplication.

Currently, `CompanyProspect` stores both identity (`name_normalized`) and run-specific data (`ai_rank`, `manual_priority`, `is_pinned`). Future refactoring will extract company identity into a separate `Company` table, but all deduplication logic MUST work correctly for both architectures.

### Canonical Identity
- **Every company has ONE canonical name**: `name_normalized` (lowercase, legal suffixes stripped iteratively)
- **Normalization is deterministic**: Same input → same normalized name every time
- **Legal suffixes removed**: `[" limited", " ltd", " llc", " inc", " pjsc", " psc", " plc", " corp"]` (order matters, iterative)
- **Company identity is global per tenant**: `(tenant_id, name_normalized)` - NOT per-run

### Deduplication Rules
- **Prospect dedupe within run**: `(tenant_id, run_id, name_normalized)` - One prospect per canonical company per run
- **Aliases do NOT create new prospects** - "Emirates" and "Emirates Airlines" → same prospect if they normalize to same canonical name
- **Re-ingesting same company into same run** → Updates existing prospect, does NOT create duplicate
- **Same company in different runs** → Separate prospects (run-scoped data like ai_rank differs)
- **Phase 1 and Phase 2 dedupe across each other** - Manual list and AI proposal both use same canonical name

### Data Constraints
- `tenant_id` MUST be present on all tenant-scoped models (enforced by `TenantScopedModel`)
- `company_research_run_id` MUST match the run being ingested into
- `metric_key` is normalized/slugified at ingest: lowercase, alphanumeric + underscore/dash, spaces→underscores. Do NOT reject; transform and store. Optionally preserve `original_key` for display.
- Exactly ONE `value_*` field populated per metric based on `value_type`

---

## 3. Evidence/Provenance Invariants

### Evidence Tracking
- **Every prospect MUST have evidence** of how it entered the system
- **Phase 1 evidence**: `source_type='manual_list'`, `list_name='List A'` or `'List B'`
- **Phase 2 evidence**: `source_type='ai_proposal_metric'` with `evidence_snippet` and `source_document_id`
- **Evidence is immutable** - Once created, evidence records are NOT deleted or modified (only added)

### Source Documents
- **Phase 2 sources** stored in `source_documents` table with `source_type='ai_proposal'`
- **Sources have temp_ids** in JSON for cross-referencing within proposal
- **Metrics reference sources** via `source_document_id` FK (nullable)

### Audit Trail
- All models have `created_at`, `updated_at` timestamps (automatic via SQLAlchemy)
- `CompanyProspect.approved_by_user_id` and `approved_at` track manual approval
- Evidence tracks `list_rank_position` for Phase 1 (preserves original order)

---

## 4. Idempotency Rules

### Re-Ingestion Behavior
- **Phase 1 re-ingest** same lists → NO new prospects if `name_normalized` already exists
- **Phase 2 re-ingest** same proposal → NO duplicate metrics if identical `(tenant, run, company, metric_key, as_of_date, source, value_type, value_*)`
- **"Identical" metric** = same values in ALL identifying fields including the typed value field

### What Re-Ingest MUST Do
- ✅ Update existing `ai_rank`, `ai_score` if company already exists
- ✅ Add new metrics if `metric_key` is different or `as_of_date` differs
- ✅ Add new aliases to `company_aliases` table
- ✅ Create new evidence records (evidence is append-only)

### What Re-Ingest MUST NOT Do
- ❌ Duplicate companies (dedupe by canonical name)
- ❌ Duplicate identical metrics (check all value_* fields)
- ❌ Overwrite user's `manual_priority` (My Rank)
- ❌ Overwrite user's `is_pinned` status
- ❌ Overwrite user's `manual_notes`
- ❌ Delete existing data

---

## 5. Ranking Invariants

### Three Ranking Systems
1. **AI Rank** (`ai_rank` integer): AI's ranking (1=best), from Phase 2 proposal
2. **My Rank** (`manual_priority` integer): User's manual override (1=highest)
3. **Rank Spec** (`rank_spec` JSONB on run): User's preferred default sort

### Ranking Precedence Rules
- **manual_priority ONLY applies in manual sort mode** - When `order_by='manual'`, sort by `is_pinned DESC, manual_priority ASC, relevance_score DESC`
- **In other sort modes, manual_priority is ignored** (except as optional tie-breaker)
- **AI Rank never overwrites My Rank** - They are separate columns with separate purposes
- **Rank Spec is per-run** - Different runs can have different default sort preferences
- **Pinned companies ALWAYS float to top** - `is_pinned=True` → top of list regardless of sort mode

### Sorting Modes
- `manual`: User's explicit ranking (pinned → manual_priority → relevance)
- `ai`: AI relevance score (pinned → relevance_score → evidence_score)
- `ai_rank`: AI-assigned rank (pinned → ai_rank → relevance_score)
- `metric:<key>`: Sort by specific metric (pinned → value_* DESC → relevance_score)

---

## 6. Multi-Tenant Invariants

### Tenant Isolation
- **ALL queries MUST filter by `tenant_id`** - No exceptions
- **Tenant ID from auth token** - `current_user.tenant_id` is source of truth
- **Cross-tenant access = security violation** - Never join across tenants
- **UUID collision impossible** - IDs are globally unique but MUST still enforce tenant filter

### Repository Pattern
- All `CompanyResearchRepository` methods take `tenant_id` as first parameter
- Services validate `tenant_id` matches authenticated user
- Database constraints: Composite indexes include `tenant_id` for query performance

---

## 7. Logging/Observability Invariants

### Minimum Required Logging
- **All ingestion operations** log: tenant_id, run_id, user_id, operation_type, counts (companies, metrics, sources)
- **Validation failures** log: tenant_id, run_id, error_type, error_path (e.g., "companies[2].metrics[1].key")
- **Dedupe events** log: tenant_id, run_id, canonical_name, action (created/updated)
- **Metric ingestion** log: tenant_id, run_id, company_id, metric_key, value_type, action (created/skipped_duplicate)

### Log Structure
- Use structured logging (JSON) for production
- Include correlation IDs for request tracing
- Log at appropriate levels: INFO (success), WARNING (dedupe), ERROR (validation/db failures)

### Observability Metrics
- Count of proposals validated (success/failure)
- Count of companies ingested (new/updated)
- Count of metrics ingested per type (number/text/bool/json)
- Ingestion latency (p50, p95, p99)

---

## 8. Performance Invariants

### No Heavy Work in Request Thread
- ❌ **NO web scraping** in sync request handlers
- ❌ **NO LLM API calls** during validation or ingestion
- ❌ **NO large file downloads** in request handlers
- ✅ All Phase 1/2 operations complete in <5 seconds for typical datasets (10-50 companies)

### Database Efficiency
- **Use batch inserts** where possible (session.add_all)
- **Limit queries in loops** - Fetch all prospects once, not per-company
- **Use joins** instead of N+1 queries (e.g., fetch metrics with prospects)
- **Indexed columns**: `tenant_id`, `company_research_run_id`, `name_normalized`, `metric_key`

### Transaction Boundaries
- **One transaction per ingestion** - Rollback entire operation on any error
- **No nested transactions** - Keep it simple
- **Explicit commit** only after all validation passes

---

## Regression Checklist (Must Pass Before Merge)

1. **Phase 1: Ingest List A with 5 companies** → 5 prospects created, 5 evidence records with `list_name='List A'`
2. **Phase 1: Re-ingest same List A** → 0 new prospects, 0 duplicates
3. **Phase 1: Ingest List B with 3 from List A + 2 new** → 2 new prospects, all 5 have evidence from both lists
4. **Phase 2: Validate sample_typed_metrics.json** → Validation passes, shows 3 companies, 12 metrics (4 per company)
5. **Phase 2: Ingest sample_typed_metrics.json** → 3 prospects, 12 metrics (all 4 types: number, bool, json, text if present)
6. **Phase 2: Re-ingest identical proposal** → 0 duplicate metrics, ai_rank/ai_score updated
7. **Sort by "Metric: Fleet Size"** → Column appears with "Fleet Size" header, values show "265 aircraft", companies sorted DESC
8. **Sort by "Metric: Is Low Cost Carrier"** → Column shows ✓/✗, true values appear first
9. **Sort by "My Manual Order"** → Metric column disappears, pinned companies float to top, manual_priority honored
10. **Cross-tenant isolation test** → User from Tenant A cannot see/access runs from Tenant B (404/403 error)

---

## Emergency Contacts

- **Breaking changes to normalization**: Requires data migration for existing prospects
- **Schema changes**: Create Alembic migration FIRST, test with existing data
- **Dedupe logic changes**: May cause duplicates if not backward-compatible

**When in doubt**: Preserve existing data, add new columns, write migration to backfill.

# Before/After: Typed Metrics Implementation

## Problem Statement

**Before**: The system hardcoded "total_assets" as the primary metric, assuming all companies were financial institutions. This made it impossible to:
- Research airlines (need fleet_size, is_low_cost_carrier)
- Research family offices (need has_real_estate_exposure, portfolio_sectors)
- Use boolean or JSON metrics
- Let users choose which metric to sort by

## Solution

Implemented a flexible, typed metrics system supporting number, text, bool, and json values with user-configurable sorting.

---

## Database Schema

### BEFORE
```sql
CREATE TABLE company_metrics (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    company_research_run_id UUID NOT NULL,
    company_prospect_id UUID NOT NULL,
    metric_key VARCHAR(200) NOT NULL,
    
    -- Only two value types supported
    value_number NUMERIC(20, 4),
    value_text TEXT,
    
    value_currency VARCHAR(10),
    as_of_date TIMESTAMP,
    confidence NUMERIC(3, 2),
    source_document_id UUID
);
```

### AFTER
```sql
CREATE TABLE company_metrics (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    company_research_run_id UUID NOT NULL,
    company_prospect_id UUID NOT NULL,
    metric_key VARCHAR(200) NOT NULL,
    
    -- Explicit type declaration
    value_type VARCHAR(20) NOT NULL, -- 'number' | 'text' | 'bool' | 'json'
    
    -- Four value types supported
    value_number NUMERIC(20, 4),
    value_text TEXT,
    value_bool BOOLEAN,
    value_json JSONB,
    
    value_currency VARCHAR(10),
    unit VARCHAR(50),  -- NEW: for number types (e.g., 'aircraft', 'employees')
    as_of_date TIMESTAMP,
    confidence NUMERIC(3, 2),
    source_document_id UUID
);

ALTER TABLE company_research_runs 
ADD COLUMN rank_spec JSONB NOT NULL DEFAULT '{}';  -- NEW: user-configurable ranking
```

---

## JSON Schema

### BEFORE
```json
{
  "key": "total_assets",
  "value_number": 5200000000,
  "value_text": null,
  "value_currency": "USD"
}
```

**Problems**:
- Unclear which field to use (value_number or value_text?)
- No support for boolean values
- No support for complex data structures
- No unit field for non-monetary numbers

### AFTER
```json
{
  "key": "fleet_size",
  "type": "number",
  "value": 265,
  "unit": "aircraft"
}
```

```json
{
  "key": "is_low_cost_carrier",
  "type": "bool",
  "value": true
}
```

```json
{
  "key": "destinations",
  "type": "json",
  "value": ["JFK", "LHR", "SYD"]
}
```

**Benefits**:
- Explicit type declaration
- Single `value` field (type-safe)
- Support for bool and json
- Unit field for measurements

---

## Code: Service Layer

### BEFORE (app/services/ai_proposal_service.py)
```python
async def _ingest_metric(self, tenant_id, run_id, prospect, metric_data, ...):
    # Hardcoded to value_number and value_text only
    metric = CompanyMetric(
        metric_key=metric_data.key,
        value_number=metric_data.value_number,  # What if it's a boolean?
        value_text=metric_data.value_text,      # What if it's JSON?
        value_currency=metric_data.value_currency,
    )
```

### AFTER
```python
async def _ingest_metric(self, tenant_id, run_id, prospect, metric_data, ...):
    # Dynamic mapping based on type
    value_number = None
    value_text = None
    value_bool = None
    value_json = None
    
    if metric_data.type == "number":
        value_number = float(metric_data.value)
    elif metric_data.type == "text":
        value_text = str(metric_data.value)
    elif metric_data.type == "bool":
        value_bool = bool(metric_data.value)
    elif metric_data.type == "json":
        value_json = metric_data.value  # Already dict/list
    
    metric = CompanyMetric(
        metric_key=metric_data.key,
        value_type=metric_data.type,
        value_number=value_number,
        value_text=value_text,
        value_bool=value_bool,
        value_json=value_json,
        value_currency=metric_data.currency,
        unit=metric_data.unit,
    )
```

---

## Code: Repository Sorting

### BEFORE (app/repositories/company_research_repo.py)
```python
elif order_by == "metric":
    # HARDCODED to total_assets
    metric_alias = aliased(CompanyMetric)
    query = query.outerjoin(
        metric_alias,
        and_(
            metric_alias.company_prospect_id == CompanyProspect.id,
            metric_alias.metric_key == "total_assets"  # HARDCODED!
        )
    ).order_by(
        desc(metric_alias.value_number).nulls_last()  # Only works for numbers
    )
```

### AFTER
```python
elif order_by.startswith("metric:"):
    # DYNAMIC: extract metric_key from "metric:fleet_size"
    metric_key = order_by.split(":", 1)[1]
    
    metric_alias = aliased(CompanyMetric)
    query = query.outerjoin(
        metric_alias,
        and_(
            metric_alias.company_prospect_id == CompanyProspect.id,
            metric_alias.metric_key == metric_key  # ANY metric
        )
    ).order_by(
        # Sort by appropriate column based on value_type
        desc(case(
            (metric_alias.value_type == 'number', metric_alias.value_number),
            (metric_alias.value_type == 'bool', cast(metric_alias.value_bool, Integer)),
            else_=None
        )).nulls_last()
    )
```

---

## Code: UI Route

### BEFORE (app/ui/routes/company_research.py)
```python
# HARDCODED total_assets query
primary_metric_query = select(CompanyMetric).where(
    CompanyMetric.metric_key == "total_assets"  # HARDCODED!
)
primary_metric = await session.execute(primary_metric_query)
# ...
prospect_dict["primary_metric"] = format_number(primary_metric.value_number)
```

### AFTER
```python
# Fetch ALL available metrics for the run
metrics_keys_query = select(CompanyMetric.metric_key).where(
    CompanyMetric.company_research_run_id == run_id,
).distinct()
available_metrics = sorted([row[0] for row in metrics_keys_result])

# Fetch ALL metrics for each prospect
all_metrics_query = select(CompanyMetric).where(
    CompanyMetric.company_prospect_id == prospect.id,
)
all_metrics = all_metrics_result.scalars().all()

# Build dynamic metrics dict
metrics_dict = {}
for metric in all_metrics:
    if metric.value_type == "number":
        metrics_dict[metric.metric_key] = format_with_suffix(metric.value_number)
    elif metric.value_type == "bool":
        metrics_dict[metric.metric_key] = "✓" if metric.value_bool else "✗"
    # ... handle text and json

prospect_dict["metrics"] = metrics_dict  # ALL metrics, not just one
```

---

## Code: UI Template

### BEFORE (company_research_run_detail.html)
```html
<select onchange="...">
    <option value="manual">My Manual Order</option>
    <option value="ai">AI Relevance</option>
    <option value="ai_rank">AI Rank</option>
    <option value="metric">Primary Metric (↓)</option>  <!-- HARDCODED -->
</select>

<th>Primary Metric</th>  <!-- Single hardcoded column -->
```

### AFTER
```html
<select onchange="...">
    <option value="manual">My Manual Order</option>
    <option value="ai">AI Relevance</option>
    <option value="ai_rank">AI Rank</option>
    {% for metric_key in available_metrics %}
    <option value="metric:{{ metric_key }}">  <!-- DYNAMIC -->
        Metric: {{ metric_key|title }} (↓)
    </option>
    {% endfor %}
</select>

<th>Metrics</th>  <!-- Shows first 3 metrics dynamically -->
```

---

## Example Use Cases

### Use Case 1: Airlines Research

**Query**: "Find low-cost carriers in UAE with fleet size > 50"

**JSON**:
```json
{
  "companies": [
    {
      "name": "Flydubai",
      "metrics": [
        {"key": "fleet_size", "type": "number", "value": 78, "unit": "aircraft"},
        {"key": "is_low_cost_carrier", "type": "bool", "value": true},
        {"key": "destinations", "type": "json", "value": ["CAI", "DEL", "IST"]}
      ]
    }
  ]
}
```

**Sorting**:
- By fleet_size: 78, 56, 45
- By is_low_cost_carrier: true companies first

### Use Case 2: NBFC Research (India)

**Query**: "Top 10 NBFCs by total assets"

**JSON**:
```json
{
  "companies": [
    {
      "name": "Bajaj Finance",
      "metrics": [
        {"key": "total_assets", "type": "number", "value": 2800000000000, "currency": "INR"},
        {"key": "has_banking_license", "type": "bool", "value": false},
        {"key": "business_segments", "type": "json", "value": ["consumer", "sme"]}
      ]
    }
  ]
}
```

**Sorting**:
- By total_assets: 2.8T INR, 1.2T INR, 900B INR

### Use Case 3: Family Office Research

**Query**: "Family offices with real estate exposure"

**JSON**:
```json
{
  "companies": [
    {
      "name": "Cascade Investment",
      "metrics": [
        {"key": "aum_estimated", "type": "number", "value": 130000000000, "currency": "USD"},
        {"key": "has_real_estate_exposure", "type": "bool", "value": true},
        {"key": "portfolio_sectors", "type": "json", "value": ["RE", "hospitality", "energy"]}
      ]
    }
  ]
}
```

**Sorting**:
- By aum_estimated: 130B USD, 50B USD, 25B USD
- By has_real_estate_exposure: true companies first

---

## Benefits

1. **Flexibility**: Support ANY industry with appropriate metrics
2. **Type Safety**: Value type explicitly declared and validated
3. **Sortability**: Users choose which metric to rank by
4. **Extensibility**: Easy to add new value types in future
5. **No Breaking Changes**: Existing data automatically migrated

---

## Testing

### Before
- ✅ Can ingest financial companies with total_assets
- ❌ Cannot ingest airlines (no fleet_size support)
- ❌ Cannot ingest boolean metrics (is_low_cost_carrier)
- ❌ Cannot ingest complex data (destinations list)
- ❌ Cannot sort by different metrics

### After
- ✅ Can ingest financial companies with total_assets
- ✅ Can ingest airlines with fleet_size, is_low_cost_carrier, destinations
- ✅ Can ingest any industry with any metric type
- ✅ Can sort by any numeric or boolean metric
- ✅ No duplicates on re-ingestion (idempotent)
- ✅ Deduplication across company name variants

---

## Migration Impact

**Existing Data**: ✅ No breakage
- All existing metrics automatically get `value_type='number'` or `value_type='text'`
- Old queries continue to work
- UI shows metrics dynamically

**New Data**: ⚠️ Schema change required
- Old JSON format with `value_number`/`value_text` will fail validation
- Must use new format with `type` and `value` fields
- See TYPED_METRICS_REFERENCE.md for examples

**API**: ✅ No breakage
- Validation endpoint works with new schema
- Ingestion endpoint works with new schema
- All Phase 1 endpoints unaffected

---

## Summary

**Problem**: Hardcoded assumptions about financial metrics
**Solution**: Flexible, typed metrics system
**Result**: Support for ANY industry with ANY metric types

The system can now handle:
- Financial: total_assets, revenue (number + currency)
- Airlines: fleet_size (number + unit), is_low_cost_carrier (bool), destinations (json)
- Family Offices: aum (number + currency), has_real_estate_exposure (bool), portfolio_sectors (json)
- Any industry with arbitrary metrics

No more "primary_metric" assumptions. Full user control.

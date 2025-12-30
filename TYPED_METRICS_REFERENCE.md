# Typed Metrics Quick Reference

## JSON Schema for AI Proposals

### Metric Types

#### Number Metric
```json
{
  "key": "fleet_size",
  "type": "number",
  "value": 265,
  "unit": "aircraft",
  "currency": null,
  "as_of_date": "2024-12-01",
  "confidence": 0.9,
  "source_temp_id": "source_1",
  "evidence_snippet": "Emirates operates 265 wide-body aircraft"
}
```

#### Number with Currency
```json
{
  "key": "total_assets",
  "type": "number",
  "value": 5200000000,
  "currency": "USD",
  "unit": null,
  "as_of_date": "2023-12-31",
  "confidence": 0.95,
  "source_temp_id": "source_1"
}
```

#### Boolean Metric
```json
{
  "key": "is_low_cost_carrier",
  "type": "bool",
  "value": true,
  "confidence": 1.0,
  "source_temp_id": "source_1"
}
```

#### Text Metric
```json
{
  "key": "primary_business_model",
  "type": "text",
  "value": "Full-service international carrier",
  "confidence": 0.9,
  "source_temp_id": "source_1"
}
```

#### JSON Metric (Array)
```json
{
  "key": "destinations",
  "type": "json",
  "value": ["JFK", "LHR", "SYD", "HKG", "SIN"],
  "confidence": 0.85,
  "source_temp_id": "source_1",
  "evidence_snippet": "Emirates serves over 150 destinations"
}
```

#### JSON Metric (Object)
```json
{
  "key": "portfolio_breakdown",
  "type": "json",
  "value": {
    "real_estate": 45,
    "equities": 30,
    "bonds": 15,
    "alternatives": 10
  },
  "confidence": 0.8,
  "source_temp_id": "source_1"
}
```

## Complete Example: Airlines

```json
{
  "query": "UAE airlines with fleet and operational data",
  "sources": [
    {
      "temp_id": "source_1",
      "title": "Aviation Industry Report 2024",
      "url": "https://example.com/report",
      "provider": "Aviation Weekly"
    }
  ],
  "companies": [
    {
      "name": "Emirates Airlines",
      "website_url": "https://www.emirates.com",
      "hq_country": "AE",
      "hq_city": "Dubai",
      "sector": "Aviation",
      "ai_rank": 1,
      "ai_score": 0.95,
      "metrics": [
        {
          "key": "fleet_size",
          "type": "number",
          "value": 265,
          "unit": "aircraft"
        },
        {
          "key": "is_low_cost_carrier",
          "type": "bool",
          "value": false
        },
        {
          "key": "destinations",
          "type": "json",
          "value": ["JFK", "LHR", "SYD", "HKG"]
        },
        {
          "key": "total_revenue",
          "type": "number",
          "value": 31500000000,
          "currency": "USD"
        }
      ]
    }
  ]
}
```

## Complete Example: NBFCs (Non-Bank Financial Companies)

```json
{
  "query": "Indian NBFCs with total assets data",
  "sources": [
    {
      "temp_id": "source_1",
      "title": "RBI Financial Stability Report 2024",
      "url": "https://rbi.org.in/report"
    }
  ],
  "companies": [
    {
      "name": "Bajaj Finance Limited",
      "hq_country": "IN",
      "hq_city": "Pune",
      "sector": "NBFC",
      "ai_rank": 1,
      "ai_score": 0.98,
      "metrics": [
        {
          "key": "total_assets",
          "type": "number",
          "value": 2800000000000,
          "currency": "INR",
          "as_of_date": "2024-03-31"
        },
        {
          "key": "loan_portfolio_size",
          "type": "number",
          "value": 2400000000000,
          "currency": "INR",
          "as_of_date": "2024-03-31"
        },
        {
          "key": "has_banking_license",
          "type": "bool",
          "value": false
        },
        {
          "key": "business_segments",
          "type": "json",
          "value": ["consumer_finance", "sme_lending", "commercial_lending"]
        }
      ]
    }
  ]
}
```

## Complete Example: Family Offices

```json
{
  "query": "UHNW family offices with real estate exposure",
  "sources": [
    {
      "temp_id": "source_1",
      "title": "Family Office Database 2024",
      "url": "https://example.com/fo-report"
    }
  ],
  "companies": [
    {
      "name": "Cascade Investment LLC",
      "hq_country": "US",
      "hq_city": "Kirkland",
      "sector": "Family Office",
      "ai_rank": 1,
      "ai_score": 0.92,
      "metrics": [
        {
          "key": "aum_estimated",
          "type": "number",
          "value": 130000000000,
          "currency": "USD",
          "as_of_date": "2024-01-01"
        },
        {
          "key": "has_real_estate_exposure",
          "type": "bool",
          "value": true
        },
        {
          "key": "portfolio_sectors",
          "type": "json",
          "value": ["real_estate", "hospitality", "energy", "technology"]
        },
        {
          "key": "investment_style",
          "type": "text",
          "value": "Long-term value investing"
        }
      ]
    }
  ]
}
```

## Sorting Behavior

### By Number Metrics
- Sorted **descending** by default (highest first)
- Example: Sort by fleet_size → 265, 78, 56

### By Boolean Metrics
- **True values first**, then false
- Example: Sort by is_low_cost_carrier → true, true, false

### By Text Metrics
- **Not yet implemented** (would be alphabetical)
- Currently disabled in UI

### By JSON Metrics
- **Not sortable** (meaningless to sort complex data)
- Currently disabled in UI

## Value Formatting in UI

### Number
- ≥ 1B: Shows as "1.5B"
- ≥ 1M: Shows as "150.0M"
- < 1M: Shows as "150,000"
- With currency: "USD 1.5B"
- With unit: "265 aircraft"

### Boolean
- True: ✓
- False: ✗

### Text
- Shows raw text (truncated if too long)

### JSON
- Shows first 50 characters + "..."
- Full value visible in database

## Validation Rules

1. **key**: Alphanumeric, underscore, dash only; lowercase
2. **type**: Must be "number", "text", "bool", or "json"
3. **value**: Must match declared type
   - number → int, float, or Decimal
   - text → string
   - bool → boolean
   - json → list or dict
4. **currency**: 3-letter uppercase ISO code (if provided)
5. **confidence**: 0.0 to 1.0 (if provided)

## Idempotency

Re-ingesting the **exact same JSON** will not create duplicate metrics.

Two metrics are considered identical if they have:
- Same tenant_id
- Same run_id
- Same company_id
- Same metric_key
- Same value_type
- Same as_of_date
- Same source_document_id
- Same value in all value_* fields

## Migration Notes

**Existing data**: All existing metrics automatically assigned `value_type='number'` or `value_type='text'` based on which column was populated.

**New proposals**: MUST include `type` field on each metric. Old format with just `value_number`/`value_text` will fail validation.

## API Endpoints

- **POST** `/api/ai-proposals/validate` - Validate JSON without ingesting
- **POST** `/api/ai-proposals/ingest?run_id={uuid}` - Validate and ingest into run

# Metric Sorting UI - How It Works

## Problem Solved

Previously, the UI showed "first 3 metrics" in a generic "Metrics" column, which was confusing because:
- Users couldn't clearly see what they were sorting by
- Multiple metrics crammed into one column was hard to read
- The column header didn't indicate which metric was being displayed

## Solution

**Dynamic Single-Metric Column**: Show ONE metric column that displays the currently selected sort metric.

## How It Works

### 1. Default View (Manual or AI Sorting)
When sorted by "My Manual Order" or "AI Relevance":
- **NO metric column shown** in the table
- Clean, simple view focused on company names and rankings

```
Table Columns:
📌 | Company Name | AI Rank | AI Score | My Rank | Evidence | Status | Actions
```

### 2. When Sorting by a Specific Metric
When you select "Metric: Fleet Size" from the dropdown:
- **ONE metric column appears** showing ONLY fleet_size values
- Column header dynamically changes to "Fleet Size"
- Table is sorted by that metric (descending for numbers, true-first for booleans)

```
Table Columns:
📌 | Company Name | Fleet Size | AI Rank | AI Score | My Rank | Evidence | Status | Actions
                    ↑
              Shows: 265 aircraft
                     78 aircraft
                     56 aircraft
```

### 3. Switching Between Metrics
When you change the dropdown to "Metric: Total Revenue":
- Column header changes to "Total Revenue"
- Column values update to show total_revenue for each company
- Table re-sorts by total_revenue (descending)

```
Table Columns:
📌 | Company Name | Total Revenue | AI Rank | AI Score | My Rank | Evidence | Status | Actions
                     ↑
              Shows: USD 31.5B
                     USD 2.8B
                     USD 1.5B
```

### 4. Boolean Metrics
When sorting by "Metric: Is Low Cost Carrier":
- Column header: "Is Low Cost Carrier"
- Values show: ✓ (true) or ✗ (false)
- True values appear first

```
Table Columns:
📌 | Company Name | Is Low Cost Carrier | AI Rank | AI Score | ...
                        ↑
                 Shows: ✓
                        ✓
                        ✗
```

## Implementation Details

### Backend (app/ui/routes/company_research.py)

```python
# Extract selected metric key from order_by parameter
selected_metric_key = None
if order_by.startswith("metric:"):
    selected_metric_key = order_by.split(":", 1)[1]  # "metric:fleet_size" -> "fleet_size"

# Pass to template
return templates.TemplateResponse(
    "company_research_run_detail.html",
    {
        "selected_metric_key": selected_metric_key,  # NEW
        "available_metrics": available_metrics,
        # ... other context
    }
)
```

### Frontend (company_research_run_detail.html)

**Dynamic Table Header:**
```html
<th>Company Name</th>
{% if selected_metric_key %}
<th>{{ selected_metric_key|replace('_', ' ')|title }}</th>  <!-- "fleet_size" -> "Fleet Size" -->
{% endif %}
```

**Dynamic Table Rows:**
```html
<td>{{ prospect.name_normalized }}</td>
{% if selected_metric_key %}
<td style="text-align: right;">
    {% if prospect.metrics.get(selected_metric_key) %}
        {{ prospect.metrics[selected_metric_key] }}  <!-- Show ONLY the selected metric -->
    {% else %}
        <span style="color: #ccc;">-</span>  <!-- Company doesn't have this metric -->
    {% endif %}
</td>
{% endif %}
```

## User Experience Flow

1. **Open research run** → See manual order, no metric column
2. **Click sort dropdown** → See all available metrics for this run:
   - Metric: Destinations
   - Metric: Fleet Size
   - Metric: Is Low Cost Carrier
   - Metric: Total Revenue
3. **Select "Metric: Fleet Size"** → Page reloads
4. **Table updates**:
   - New column appears: "Fleet Size"
   - Shows values: "265 aircraft", "78 aircraft", "56 aircraft"
   - Companies sorted by fleet size descending
   - URL: `?order_by=metric:fleet_size`
5. **Select "Metric: Is Low Cost Carrier"** → Page reloads
6. **Table updates**:
   - Column header changes to "Is Low Cost Carrier"
   - Shows values: ✓, ✓, ✗
   - True values appear first
   - URL: `?order_by=metric:is_low_cost_carrier`

## Benefits

✅ **Clarity**: Always clear what metric you're looking at
✅ **Simplicity**: One metric at a time, no clutter
✅ **Flexibility**: Any metric can be the sort key
✅ **Clean Layout**: Column only appears when needed
✅ **Type-Aware**: Format matches metric type (number with units, boolean as ✓/✗, etc.)

## Future Enhancements

- **Multi-column view**: Show top 3 metrics as separate columns
- **Metric details modal**: Click to see all metrics for a company
- **Sticky column selection**: Remember user's preferred metric per run
- **Metric filtering**: "Show only companies where fleet_size > 100"

## Edge Cases Handled

- **Company missing metric**: Shows "-" instead of empty cell
- **No metrics in run**: Metric column never appears
- **JSON metrics**: Shows truncated JSON (full value in DB)
- **Very long metric names**: Column header wraps gracefully

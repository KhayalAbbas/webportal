# Candidate Search API - Quick Reference

## Overview

The Candidate Search API allows you to search your internal candidate database with full-text search and structured filters. All endpoints require JWT authentication and enforce tenant isolation.

## Endpoint

```
GET /search/candidates
```

**Authentication:** Required (JWT Bearer token)  
**Tenant Header:** Required (`X-Tenant-ID`)

## Query Parameters

### Full-Text Search

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `q` | string | Free-text search across name, title, company, bio, tags, CV text | `senior python aws` |

### Structured Filters (All Optional)

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `home_country` | string | Filter by home country (partial match) | `United States` |
| `location` | string | Filter by location (partial match) | `London` |
| `current_title` | string | Filter by current title (partial match) | `Director` |
| `current_company` | string | Filter by current company (partial match) | `Google` |
| `languages` | string | Filter by languages (partial match) | `English` |
| `promotability_min` | integer | Minimum promotability score (0-100) | `70` |
| `promotability_max` | integer | Maximum promotability score (0-100) | `90` |
| `assignment_role_id` | UUID | Only return candidates assigned to this role | `123e4567-e89b-12d3-a456-426614174000` |
| `assignment_status` | string | Filter by assignment status (requires `assignment_role_id`) | `SHORT_LIST` |

### Pagination

| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `limit` | integer | 50 | 200 | Number of results per page |
| `offset` | integer | 0 | - | Number of results to skip |

## Response Format

```json
{
  "items": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "first_name": "John",
      "last_name": "Doe",
      "current_title": "Senior Software Engineer",
      "current_company": "Tech Corp",
      "location": "San Francisco, CA",
      "home_country": "United States",
      "languages": "English, Spanish",
      "tags": "python, aws, kubernetes",
      "promotability_score": 85,
      "technical_score": 90,
      "gamification_score": 75,
      "email": "john.doe@example.com",
      "phone": "+1-555-0123",
      "linkedin_url": "https://linkedin.com/in/johndoe",
      "bio_snippet": "Experienced software engineer with 10 years in cloud infrastructure...",
      "assignment_status": "SHORT_LIST",
      "assignment_is_hot": true,
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-03-20T14:45:00Z"
    }
  ],
  "total": 156,
  "limit": 50,
  "offset": 0
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | List of candidate search results |
| `total` | integer | Total number of matches (for pagination) |
| `limit` | integer | Results per page (echoed back) |
| `offset` | integer | Results skipped (echoed back) |

### Candidate Result Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Candidate ID |
| `first_name`, `last_name` | string | Candidate name |
| `current_title`, `current_company` | string | Current position |
| `location`, `home_country` | string | Location information |
| `languages`, `tags` | string | Skills and attributes |
| `promotability_score`, `technical_score`, `gamification_score` | integer | Assessment scores |
| `email`, `phone`, `linkedin_url` | string | Contact information |
| `bio_snippet` | string | First 300 characters of bio |
| `assignment_status`, `assignment_is_hot` | string, boolean | Assignment info (only when filtering by `assignment_role_id`) |
| `created_at`, `updated_at` | datetime | Metadata timestamps |

## Ranking Logic

### With Text Search (`q` parameter)
Results are sorted by:
1. **Full-text relevance score** (PostgreSQL `ts_rank`)
2. **Promotability score** (descending, nulls last)
3. **Updated date** (descending - most recent first)

### Without Text Search
Results are sorted by:
1. **Promotability score** (descending, nulls last)
2. **Updated date** (descending - most recent first)

## Example Requests

### 1. Simple Text Search

```powershell
$token = "your-jwt-token"
$tenantId = "your-tenant-id"

$headers = @{
    "Authorization" = "Bearer $token"
    "X-Tenant-ID" = $tenantId
}

Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?q=senior+python+aws" `
    -Method Get -Headers $headers
```

**URL:** `/search/candidates?q=senior+python+aws`

Searches for candidates with "senior", "python", and "aws" in their profile.

---

### 2. Filter by Location and Promotability

```powershell
$params = @{
    home_country = "United Kingdom"
    promotability_min = 75
    limit = 20
}

$queryString = ($params.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString($_.Value))" }) -join "&"

Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?$queryString" `
    -Method Get -Headers $headers
```

**URL:** `/search/candidates?home_country=United+Kingdom&promotability_min=75&limit=20`

Returns top 20 UK-based candidates with promotability score ≥ 75.

---

### 3. Search Candidates for Specific Role

```powershell
$roleId = "123e4567-e89b-12d3-a456-426614174000"

Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?q=director+finance&assignment_role_id=$roleId&assignment_status=SHORT_LIST" `
    -Method Get -Headers $headers
```

**URL:** `/search/candidates?q=director+finance&assignment_role_id=123e4567-e89b-12d3-a456-426614174000&assignment_status=SHORT_LIST`

Searches for candidates with "director" and "finance" who are on the SHORT_LIST for a specific role.

---

### 4. Combined Filters

```powershell
$params = @{
    q = "senior engineer"
    home_country = "Canada"
    current_company = "Amazon"
    languages = "French"
    promotability_min = 80
    limit = 30
    offset = 0
}

$queryString = ($params.GetEnumerator() | ForEach-Object { "$($_.Key)=$([uri]::EscapeDataString($_.Value))" }) -join "&"

Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?$queryString" `
    -Method Get -Headers $headers
```

**URL:** `/search/candidates?q=senior+engineer&home_country=Canada&current_company=Amazon&languages=French&promotability_min=80&limit=30&offset=0`

Complex search: senior engineers from Canada, currently at Amazon, speak French, with high promotability scores.

---

### 5. Pagination Example

```powershell
# First page
Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?q=python&limit=50&offset=0" `
    -Method Get -Headers $headers

# Second page
Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?q=python&limit=50&offset=50" `
    -Method Get -Headers $headers

# Third page
Invoke-RestMethod -Uri "http://localhost:8000/search/candidates?q=python&limit=50&offset=100" `
    -Method Get -Headers $headers
```

---

## Database Performance

The search endpoint uses PostgreSQL full-text search with the following optimizations:

- **GIN index** on generated `tsvector` column for fast full-text search
- **Composite indexes** on tenant_id + filter fields (home_country, location, title, company, promotability)
- **Generated column** automatically maintains search_vector (includes first_name, last_name, current_title, current_company, bio, tags, cv_text)
- **Text weights** for relevance ranking:
  - **A (highest):** first_name, last_name
  - **B:** current_title, current_company, tags
  - **C:** bio
  - **D (lowest):** cv_text

---

## Error Responses

### 401 Unauthorized
```json
{
  "detail": "Not authenticated"
}
```
Missing or invalid JWT token.

### 403 Forbidden
```json
{
  "detail": "Access forbidden: user does not belong to this tenant"
}
```
User's tenant doesn't match X-Tenant-ID header.

### 422 Validation Error
```json
{
  "detail": [
    {
      "loc": ["query", "promotability_min"],
      "msg": "ensure this value is greater than or equal to 0",
      "type": "value_error.number.not_ge"
    }
  ]
}
```
Invalid query parameter format or value.

---

## Tips

1. **Combine text and filters**: Use `q` for broad search, then narrow with filters
2. **Use pagination**: Always specify `limit` and `offset` for large result sets
3. **Role-based search**: Use `assignment_role_id` to find candidates already in your pipeline
4. **Score filtering**: Use `promotability_min`/`max` to find top-tier candidates
5. **Partial matching**: All text filters use case-insensitive partial matching (ILIKE)

---

## Migration Required

Before using the search endpoint, run the database migration:

```powershell
C:/ATS/.venv/Scripts/python.exe -m alembic upgrade head
```

This creates:
- The `search_vector` generated column on the `candidate` table
- GIN and composite indexes for optimal search performance

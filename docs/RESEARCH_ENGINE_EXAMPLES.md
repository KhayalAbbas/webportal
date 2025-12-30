# Agentic Research Engine - API Examples

## Overview

The Research Engine module enables tracking research activities, storing source documents, and managing AI-generated enrichments for candidates, companies, and roles.

## Test Scenario

Let's research a candidate named "John Doe" by:
1. Creating a research event (LinkedIn profile scrape)
2. Storing source documents from that research
3. Saving AI-generated insights
4. Retrieving all research data in one call

---

## Prerequisites

**Assume you have:**
- Tenant ID: `b3909011-8bd3-439d-a421-3b70fae124e9`
- Admin token from login
- Candidate ID: Let's say you created one with ID `12345678-1234-1234-1234-123456789abc`

**PowerShell Setup:**
```powershell
$tenantId = "b3909011-8bd3-439d-a421-3b70fae124e9"
$token = "YOUR_JWT_TOKEN_HERE"
$candidateId = "12345678-1234-1234-1234-123456789abc"

$headers = @{
    "X-Tenant-ID" = $tenantId
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}
```

---

## 1. Create a Research Event

**Endpoint:** `POST /research-events`

**Purpose:** Record that you researched John Doe's LinkedIn profile

```powershell
$researchEventBody = @{
    entity_type = "CANDIDATE"
    entity_id = $candidateId
    source_type = "LINKEDIN"
    source_url = "https://linkedin.com/in/johndoe"
    raw_payload = @{
        profile_views = 523
        connections = 1200
        last_updated = "2024-12-09"
    }
} | ConvertTo-Json

$researchEvent = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/research-events" `
    -Method POST `
    -Headers $headers `
    -Body $researchEventBody

$researchEventId = $researchEvent.id
Write-Host "Created research event: $researchEventId"
```

**Response:**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
  "entity_type": "CANDIDATE",
  "entity_id": "12345678-1234-1234-1234-123456789abc",
  "source_type": "LINKEDIN",
  "source_url": "https://linkedin.com/in/johndoe",
  "raw_payload": {
    "profile_views": 523,
    "connections": 1200,
    "last_updated": "2024-12-09"
  },
  "created_at": "2024-12-09T15:30:00Z",
  "updated_at": "2024-12-09T15:30:00Z"
}
```

---

## 2. Add Source Documents

**Endpoint:** `POST /source-documents`

**Purpose:** Store the actual content scraped from LinkedIn

### Document 1: Profile Summary
```powershell
$doc1Body = @{
    research_event_id = $researchEventId
    document_type = "HTML"
    title = "John Doe LinkedIn Profile - Summary"
    url = "https://linkedin.com/in/johndoe"
    text_content = @"
Senior Software Engineer at TechCorp Inc.
San Francisco Bay Area | 1,200+ connections

About:
Passionate full-stack developer with 8+ years building scalable web applications.
Expert in Python, React, AWS. Led teams of 5-10 engineers.

Experience:
- Senior Software Engineer @ TechCorp Inc. (2020-Present)
- Software Engineer @ StartupXYZ (2016-2020)
- Junior Developer @ WebAgency (2015-2016)

Education:
BS Computer Science, Stanford University (2015)

Skills: Python, JavaScript, React, Node.js, AWS, Docker, PostgreSQL
"@
    metadata = @{
        scraped_at = "2024-12-09T15:30:00Z"
        scraper_version = "v2.1"
        content_type = "profile_summary"
    }
} | ConvertTo-Json -Depth 5

$doc1 = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/source-documents" `
    -Method POST `
    -Headers $headers `
    -Body $doc1Body

Write-Host "Created document 1: $($doc1.id)"
```

### Document 2: Recent Activity
```powershell
$doc2Body = @{
    research_event_id = $researchEventId
    document_type = "TEXT"
    title = "John Doe LinkedIn - Recent Posts"
    text_content = @"
Post 1 (Dec 5, 2024):
Just shipped a major feature at TechCorp using microservices architecture!
Reduced API latency by 40%. #engineering #performance

Post 2 (Nov 28, 2024):
Speaking at PyConf next month about building scalable data pipelines with Airflow.

Post 3 (Nov 15, 2024):
Grateful to lead an amazing team. Hiring 2 more engineers - DM if interested!
"@
    metadata = @{
        post_count = 3
        date_range = "Nov-Dec 2024"
    }
} | ConvertTo-Json -Depth 5

$doc2 = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/source-documents" `
    -Method POST `
    -Headers $headers `
    -Body $doc2Body

Write-Host "Created document 2: $($doc2.id)"
```

**Response (Document 1):**
```json
{
  "id": "doc-uuid-1",
  "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
  "research_event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "document_type": "HTML",
  "title": "John Doe LinkedIn Profile - Summary",
  "url": "https://linkedin.com/in/johndoe",
  "storage_path": null,
  "text_content": "Senior Software Engineer at TechCorp Inc...",
  "metadata": {
    "scraped_at": "2024-12-09T15:30:00Z",
    "scraper_version": "v2.1",
    "content_type": "profile_summary"
  },
  "created_at": "2024-12-09T15:31:00Z",
  "updated_at": "2024-12-09T15:31:00Z"
}
```

---

## 3. Store AI Enrichments

**Endpoint:** `POST /ai-enrichments`

**Purpose:** Save AI-generated analysis of the candidate

### Enrichment 1: Summary
```powershell
$aiSummaryBody = @{
    target_type = "CANDIDATE"
    target_id = $candidateId
    model_name = "gpt-4"
    enrichment_type = "SUMMARY"
    payload = @{
        summary = "Highly experienced Senior Software Engineer with 8+ years in full-stack development. Strong Python and JavaScript expertise with proven leadership experience. Currently at TechCorp Inc. showing active engagement in tech community through speaking and posting."
        key_strengths = @(
            "8+ years full-stack experience"
            "Team leadership (5-10 engineers)"
            "Python, React, AWS expert"
            "Active in tech community"
            "Stanford CS degree"
        )
        seniority_level = "Senior"
        fit_score = 0.87
    }
} | ConvertTo-Json -Depth 5

$aiSummary = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/ai-enrichments" `
    -Method POST `
    -Headers $headers `
    -Body $aiSummaryBody

Write-Host "Created AI summary: $($aiSummary.id)"
```

### Enrichment 2: Competency Map
```powershell
$aiCompetencyBody = @{
    target_type = "CANDIDATE"
    target_id = $candidateId
    model_name = "claude-3-opus"
    enrichment_type = "COMPETENCY_MAP"
    payload = @{
        technical_skills = @{
            python = @{ level = "expert"; years = 8; confidence = 0.95 }
            javascript = @{ level = "expert"; years = 8; confidence = 0.92 }
            react = @{ level = "expert"; years = 6; confidence = 0.90 }
            aws = @{ level = "advanced"; years = 5; confidence = 0.88 }
            docker = @{ level = "intermediate"; years = 4; confidence = 0.75 }
        }
        soft_skills = @{
            leadership = @{ level = "strong"; evidence = "Led teams of 5-10"; confidence = 0.85 }
            communication = @{ level = "strong"; evidence = "Public speaking, active posting"; confidence = 0.82 }
            collaboration = @{ level = "good"; evidence = "Team mentions"; confidence = 0.70 }
        }
        overall_assessment = "Senior-level IC with growing leadership capabilities"
    }
} | ConvertTo-Json -Depth 10

$aiCompetency = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/ai-enrichments" `
    -Method POST `
    -Headers $headers `
    -Body $aiCompetencyBody

Write-Host "Created AI competency map: $($aiCompetency.id)"
```

**Response (AI Summary):**
```json
{
  "id": "enrich-uuid-1",
  "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
  "target_type": "CANDIDATE",
  "target_id": "12345678-1234-1234-1234-123456789abc",
  "model_name": "gpt-4",
  "enrichment_type": "SUMMARY",
  "payload": {
    "summary": "Highly experienced Senior Software Engineer...",
    "key_strengths": [
      "8+ years full-stack experience",
      "Team leadership (5-10 engineers)",
      "Python, React, AWS expert",
      "Active in tech community",
      "Stanford CS degree"
    ],
    "seniority_level": "Senior",
    "fit_score": 0.87
  },
  "created_at": "2024-12-09T15:35:00Z"
}
```

---

## 4. Retrieve All Research Data

**Endpoint:** `GET /candidates/{candidate_id}/research`

**Purpose:** Get everything in one call for the UI

```powershell
$allResearch = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/candidates/$candidateId/research" `
    -Method GET `
    -Headers $headers

Write-Host "Research Events: $($allResearch.research_events.Count)"
Write-Host "Source Documents: $($allResearch.source_documents.Count)"
Write-Host "AI Enrichments: $($allResearch.ai_enrichments.Count)"
```

**Response:**
```json
{
  "research_events": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
      "entity_type": "CANDIDATE",
      "entity_id": "12345678-1234-1234-1234-123456789abc",
      "source_type": "LINKEDIN",
      "source_url": "https://linkedin.com/in/johndoe",
      "raw_payload": {
        "profile_views": 523,
        "connections": 1200,
        "last_updated": "2024-12-09"
      },
      "created_at": "2024-12-09T15:30:00Z",
      "updated_at": "2024-12-09T15:30:00Z"
    }
  ],
  "source_documents": [
    {
      "id": "doc-uuid-1",
      "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
      "research_event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "document_type": "HTML",
      "title": "John Doe LinkedIn Profile - Summary",
      "url": "https://linkedin.com/in/johndoe",
      "storage_path": null,
      "text_content": "Senior Software Engineer at TechCorp Inc...",
      "metadata": {
        "scraped_at": "2024-12-09T15:30:00Z",
        "scraper_version": "v2.1"
      },
      "created_at": "2024-12-09T15:31:00Z",
      "updated_at": "2024-12-09T15:31:00Z"
    },
    {
      "id": "doc-uuid-2",
      "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
      "research_event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "document_type": "TEXT",
      "title": "John Doe LinkedIn - Recent Posts",
      "url": null,
      "storage_path": null,
      "text_content": "Post 1 (Dec 5, 2024)...",
      "metadata": {
        "post_count": 3,
        "date_range": "Nov-Dec 2024"
      },
      "created_at": "2024-12-09T15:32:00Z",
      "updated_at": "2024-12-09T15:32:00Z"
    }
  ],
  "ai_enrichments": [
    {
      "id": "enrich-uuid-1",
      "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
      "target_type": "CANDIDATE",
      "target_id": "12345678-1234-1234-1234-123456789abc",
      "model_name": "gpt-4",
      "enrichment_type": "SUMMARY",
      "payload": {
        "summary": "Highly experienced Senior Software Engineer...",
        "key_strengths": [...],
        "seniority_level": "Senior",
        "fit_score": 0.87
      },
      "created_at": "2024-12-09T15:35:00Z"
    },
    {
      "id": "enrich-uuid-2",
      "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
      "target_type": "CANDIDATE",
      "target_id": "12345678-1234-1234-1234-123456789abc",
      "model_name": "claude-3-opus",
      "enrichment_type": "COMPETENCY_MAP",
      "payload": {
        "technical_skills": {...},
        "soft_skills": {...},
        "overall_assessment": "Senior-level IC with growing leadership capabilities"
      },
      "created_at": "2024-12-09T15:36:00Z"
    }
  ]
}
```

---

## Additional Query Examples

### List All Research Events for Candidates
```powershell
$events = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/research-events?entity_type=CANDIDATE&limit=100" `
    -Method GET `
    -Headers $headers
```

### Find LinkedIn Research Events
```powershell
$linkedInEvents = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/research-events?source_type=LINKEDIN" `
    -Method GET `
    -Headers $headers
```

### Get All Source Documents for a Research Event
```powershell
$docs = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/source-documents?research_event_id=$researchEventId" `
    -Method GET `
    -Headers $headers
```

### Find All GPT-4 Summaries
```powershell
$summaries = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/ai-enrichments?model_name=gpt-4&enrichment_type=SUMMARY" `
    -Method GET `
    -Headers $headers
```

### Get Company Research
```powershell
$companyResearch = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/companies/$companyId/research" `
    -Method GET `
    -Headers $headers
```

### Get Role Research
```powershell
$roleResearch = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/roles/$roleId/research" `
    -Method GET `
    -Headers $headers
```

---

## Enum Values Reference

### Entity Types
- `CANDIDATE`
- `COMPANY`
- `ROLE`
- `DOCUMENT` (for AI enrichments only)

### Source Types
- `WEB` - General web scraping
- `LINKEDIN` - LinkedIn profiles/data
- `INTERNAL_DB` - Internal database lookup
- `MANUAL` - Manually entered
- `OTHER` - Other sources

### Document Types
- `PDF` - PDF documents
- `HTML` - Web pages
- `TEXT` - Plain text
- `TRANSCRIPT` - Interview/call transcripts

### Enrichment Types
- `SUMMARY` - AI-generated summary
- `COMPETENCY_MAP` - Skills/competencies analysis
- `TAGGING` - Automatic tags/categories
- `RISK_FLAGS` - Risk assessment
- `OTHER` - Custom enrichment types

---

## Authentication & Security

All endpoints require:
- `X-Tenant-ID` header with tenant UUID
- `Authorization: Bearer <token>` header with valid JWT
- User must belong to the tenant specified in X-Tenant-ID

All data is automatically scoped to the authenticated user's tenant - no cross-tenant data access possible.

---

## Integration Pattern

**Typical AI Agent Workflow:**

```powershell
# 1. Agent scrapes LinkedIn
$scrapedData = Start-LinkedInScrape -ProfileUrl "..."

# 2. Create research event
$event = New-ResearchEvent -EntityType CANDIDATE -EntityId $candidateId `
    -SourceType LINKEDIN -RawPayload $scrapedData

# 3. Store scraped content
$doc = New-SourceDocument -ResearchEventId $event.id `
    -DocumentType HTML -TextContent $scrapedData.html

# 4. Call AI for analysis
$aiAnalysis = Invoke-GPT4 -Prompt "Analyze this candidate..." -Context $doc.text_content

# 5. Store AI results
$enrichment = New-AIEnrichment -TargetType CANDIDATE -TargetId $candidateId `
    -ModelName "gpt-4" -EnrichmentType SUMMARY -Payload $aiAnalysis

# 6. UI retrieves everything
$allData = Get-EntityResearch -Type Candidate -Id $candidateId
```

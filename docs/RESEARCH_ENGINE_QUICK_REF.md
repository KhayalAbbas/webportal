# Research Engine - Quick Reference Card

## 🎯 Core Concepts

**3 Main Entities:**
1. **ResearchEvent** - Track when/where research happened
2. **SourceDocument** - Store actual content (text, HTML, etc.)
3. **AIEnrichment** - Save AI-generated insights

**Relationships:**
```
ResearchEvent (LinkedIn scrape)
    └── SourceDocument (profile text)
    
Candidate
    └── AIEnrichment (GPT-4 summary)
```

---

## 🔗 Quick Endpoints

### Create Research Event
```
POST /research-events
Body: { entity_type, entity_id, source_type, source_url, raw_payload }
```

### Store Document
```
POST /source-documents
Body: { research_event_id, document_type, title, text_content, metadata }
```

### Save AI Insight
```
POST /ai-enrichments
Body: { target_type, target_id, model_name, enrichment_type, payload }
```

### Get All Research
```
GET /candidates/{id}/research
GET /companies/{id}/research
GET /roles/{id}/research
```

---

## 📋 Enum Values

**entity_type / target_type:**
- `CANDIDATE`
- `COMPANY`
- `ROLE`
- `DOCUMENT` (AI enrichments only)

**source_type:**
- `WEB` - Web scraping
- `LINKEDIN` - LinkedIn data
- `INTERNAL_DB` - Database lookup
- `MANUAL` - Manual entry
- `OTHER`

**document_type:**
- `HTML` - Web pages
- `TEXT` - Plain text
- `PDF` - PDF documents
- `TRANSCRIPT` - Transcripts

**enrichment_type:**
- `SUMMARY` - AI summary
- `COMPETENCY_MAP` - Skills map
- `TAGGING` - Auto tags
- `RISK_FLAGS` - Risk analysis
- `OTHER`

---

## 💻 PowerShell Snippets

### Setup
```powershell
$tenantId = "your-tenant-id"
$token = "your-jwt-token"
$headers = @{
    "X-Tenant-ID" = $tenantId
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}
```

### Create Event
```powershell
$event = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/research-events" `
    -Method POST `
    -Headers $headers `
    -Body (@{
        entity_type = "CANDIDATE"
        entity_id = $candidateId
        source_type = "LINKEDIN"
        source_url = "https://linkedin.com/in/username"
    } | ConvertTo-Json)
```

### Store Document
```powershell
$doc = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/source-documents" `
    -Method POST `
    -Headers $headers `
    -Body (@{
        research_event_id = $event.id
        document_type = "HTML"
        title = "Profile Data"
        text_content = "Profile content here..."
        metadata = @{ scraped_at = (Get-Date).ToString() }
    } | ConvertTo-Json -Depth 5)
```

### Save AI Result
```powershell
$ai = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/ai-enrichments" `
    -Method POST `
    -Headers $headers `
    -Body (@{
        target_type = "CANDIDATE"
        target_id = $candidateId
        model_name = "gpt-4"
        enrichment_type = "SUMMARY"
        payload = @{
            summary = "AI analysis here..."
            score = 0.85
        }
    } | ConvertTo-Json -Depth 5)
```

### Get All Research
```powershell
$research = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/candidates/$candidateId/research" `
    -Method GET `
    -Headers $headers
```

---

## 🔍 Query Filters

### Research Events
```
?entity_type=CANDIDATE
&entity_id=<uuid>
&source_type=LINKEDIN
&date_from=2024-01-01T00:00:00Z
&date_to=2024-12-31T23:59:59Z
&limit=50&skip=0
```

### Source Documents
```
?research_event_id=<uuid>
&document_type=HTML
&target_entity_type=CANDIDATE
&target_entity_id=<uuid>
&limit=50&skip=0
```

### AI Enrichments
```
?target_type=CANDIDATE
&target_id=<uuid>
&enrichment_type=SUMMARY
&model_name=gpt-4
&date_from=2024-01-01T00:00:00Z
&limit=50&skip=0
```

---

## 🎨 Response Format

**EntityResearchData:**
```json
{
  "research_events": [...],
  "source_documents": [...],
  "ai_enrichments": [...]
}
```

**ResearchEvent:**
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "entity_type": "CANDIDATE",
  "entity_id": "uuid",
  "source_type": "LINKEDIN",
  "source_url": "https://...",
  "raw_payload": {},
  "created_at": "...",
  "updated_at": "..."
}
```

**SourceDocument:**
```json
{
  "id": "uuid",
  "research_event_id": "uuid",
  "document_type": "HTML",
  "title": "...",
  "text_content": "...",
  "metadata": {},
  ...
}
```

**AIEnrichment:**
```json
{
  "id": "uuid",
  "target_type": "CANDIDATE",
  "target_id": "uuid",
  "model_name": "gpt-4",
  "enrichment_type": "SUMMARY",
  "payload": { ... },
  "created_at": "..."
}
```

---

## 🔐 Security

All endpoints require:
- ✅ JWT token in Authorization header
- ✅ X-Tenant-ID header
- ✅ User belongs to specified tenant
- ✅ All data scoped to tenant

---

## 📚 Full Docs

- **Examples**: `docs/RESEARCH_ENGINE_EXAMPLES.md`
- **Summary**: `docs/RESEARCH_ENGINE_SUMMARY.md`
- **API Docs**: http://127.0.0.1:8000/docs

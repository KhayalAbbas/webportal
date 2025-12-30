# Phase 3 Bundle Upload Tool - How to Run

This guide shows how to use the Phase 3 bundle upload tool to upload RunBundle JSON files to the API.

## Single Command (Recommended)

For the simplest workflow, use the built-in login feature:

```powershell
cd C:\ATS
$env:ATS_EMAIL="admin@test.com"
$env:ATS_PASSWORD="admin123" 
$env:ATS_TENANT_ID="b3909011-8bd3-439d-a421-3b70fae124e9"
python tools\phase3_upload_bundle.py --login --objective "Your research objective" --bundle "path\to\bundle.json"
```

This single command will:
1. ✅ Login automatically using environment credentials
2. ✅ Create a new research run with your objective  
3. ✅ Validate the bundle locally (SHA256, step types, evidence requirements)
4. ✅ Upload the bundle to the API
5. ✅ Verify the upload was successful and show run status

## Prerequisites

1. **Python 3.7+** installed
2. **Required dependencies** installed:
   ```powershell
   pip install httpx
   ```
3. **API server running** (default: http://localhost:8000)
4. **Valid RunBundle JSON file** prepared

## Basic Usage

### Option 1: Upload to Existing Run

If you already have a research run ID:

```powershell
cd C:\ATS
python tools\phase3_upload_bundle.py --bundle "path\to\your\bundle.json" --run-id "your-run-id-here"
```

### Option 2: Create New Run and Upload

If you want to create a new research run:

```powershell
cd C:\ATS
python tools\phase3_upload_bundle.py --bundle "path\to\your\bundle.json" --objective "Your research objective here"
```

## Command Line Options

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `--bundle` | ✅ Yes | Path to your bundle JSON file | `--bundle "C:\data\my_bundle.json"` |
| `--run-id` | ⚠️ Maybe | Existing run ID to upload to | `--run-id "123e4567-e89b-12d3-a456-426614174000"` |
| `--objective` | ⚠️ Maybe | Objective for new run (required if no --run-id) | `--objective "Find tech companies in San Francisco"` |
| `--base-url` | ❌ No | API server URL (default: http://localhost:8000) | `--base-url "https://api.mycompany.com"` |
| `--idempotency-key` | ❌ No | Unique key to prevent duplicate runs | `--idempotency-key "upload-2024-12-27"` |
| `--no-verify` | ❌ No | Skip verification after upload | `--no-verify` |

## Authentication

If your API requires authentication, set the `ATS_TOKEN` environment variable:

```powershell
$env:ATS_TOKEN="your-jwt-token-here"
python tools\phase3_upload_bundle.py --bundle "bundle.json" --objective "Test upload"
```

## Complete Examples

### Example 1: Simple Upload with New Run

```powershell
cd C:\ATS
python tools\phase3_upload_bundle.py --bundle "bundle.json" --objective "Test Phase 3 upload"
```

Expected output:
```
Created research run: 123e4567-e89b-12d3-a456-426614174000
Validating bundle locally...
Bundle validation passed
Uploading bundle to run 123e4567-e89b-12d3-a456-426614174000...
Upload response:
{
  "run_id": "123e4567-e89b-12d3-a456-426614174000",
  "bundle_sha256": "abc123...",
  "status": "submitted",
  "message": "Bundle accepted and ingested"
}

Verifying run status...
Run status: submitted
Steps: 3 total
  - s1: validate (ok)
  - s2: search (queued)
  - s3: finalize (queued)

Success!
```

### Example 2: Upload to Existing Run with Authentication

```powershell
cd C:\ATS
$env:ATS_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
python tools\phase3_upload_bundle.py --bundle "C:\data\my_bundle.json" --run-id "existing-run-id-123"
```

### Example 3: Upload to Remote Server

```powershell
cd C:\ATS
python tools\phase3_upload_bundle.py --base-url "https://api.production.com" --bundle "bundle.json" --objective "Production upload"
```

## Validation Checks

The tool performs these validation checks **before** uploading:

✅ **Version Check**: Bundle version must be "run_bundle_v1"  
✅ **Step Types**: Must be one of: search, fetch, extract, validate, compose, finalize  
✅ **Step Status**: Must be one of: queued, running, ok, failed, skipped  
✅ **Content Text**: All sources must have non-empty content_text  
✅ **SHA256 Integrity**: Computed SHA256 must match declared SHA256 for each source  
✅ **Evidence Requirements**: Each company must have ≥1 evidence_snippet and ≥1 source_sha256  
✅ **Reference Integrity**: All company source_sha256s must exist in the sources array  

## Error Handling

### Exit Codes
- **0**: Success
- **1**: Validation error, missing file, or HTTP error

### Common Errors

**Missing bundle file:**
```
ERROR: Bundle file not found: nonexistent.json
```

**Validation failure:**
```
VALIDATION ERRORS:
  - Step 1: Invalid step_type 'invalid'. Must be one of {'search', 'fetch', 'extract', 'validate', 'compose', 'finalize'}
  - Source 1: SHA256 mismatch. Computed: abc123, Declared: def456
```

**API error:**
```
ERROR: Failed to upload bundle (HTTP 400)
Response: {"detail": "Invalid bundle format"}
```

## Tips for Non-Developers

1. **Use quotes** around file paths with spaces: `--bundle "C:\My Documents\bundle.json"`

2. **Check your JSON** is valid before uploading (use an online JSON validator)

3. **Start small** - test with a simple bundle first

4. **Keep backups** of your bundle files

5. **Check server status** if uploads fail:
   ```powershell
   try { Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 5 | Out-Null; Write-Host "Server is running" } catch { Write-Host "Server is not running" }
   ```

## Troubleshooting

### Server Not Running
```powershell
# Start the server in a separate terminal
cd C:\ATS
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ats_db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Permission Issues
Run PowerShell as Administrator if you encounter file permission errors.

### Python Not Found
Ensure Python is installed and in your PATH, or use the full path:
```powershell
C:\Python\python.exe tools\phase3_upload_bundle.py --bundle bundle.json --objective "Test"
```
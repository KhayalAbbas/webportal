# Phase 3.4 Raw Proof Outputs

## 1) Migration Applied
```
PS C:\ATS> C:/ATS/.venv/Scripts/alembic current
c06d212c49af (head)

PS C:\ATS> C:/ATS/.venv/Scripts/python.exe show_table_structure.py
Column Name          Data Type                      Nullable
----------------------------------------------------------------------
run_id               uuid                           NO
job_type             character varying              NO
status               character varying              NO
attempts             integer                        NO
max_attempts         integer                        NO
locked_at            timestamp with time zone       YES
locked_by            character varying              YES
last_error           text                           YES
payload_json         jsonb                          NO
id                   uuid                           NO
tenant_id            uuid                           NO
created_at           timestamp with time zone       NO
updated_at           timestamp with time zone       NO
retry_at             timestamp with time zone       YES
```

## 2) Success Path Test (Incomplete - Missing CompanyResearchRun Link)
```
PS C:\ATS> C:/ATS/.venv/Scripts/python.exe simple_success_test.py
SELECT COUNT(*) FROM company_prospects WHERE tenant_id='44444444-4444-4444-4444-444444444444';
0

SELECT id,status FROM research_runs WHERE id='55555555-5555-5555-5555-555555555555';
55555555-5555-5555-5555-555555555555 | needs_review

SELECT COUNT(*) FROM research_run_bundles WHERE run_id='55555555-5555-5555-5555-555555555555';
1

SELECT id,status FROM research_runs WHERE id='55555555-5555-5555-5555-555555555555';
55555555-5555-5555-5555-555555555555 | ingesting

SELECT id,job_type,status,attempts,max_attempts,retry_at,locked_by,locked_at,last_error FROM research_jobs WHERE run_id='55555555-5555-5555-5555-555555555555' ORDER BY created_at DESC LIMIT 1;
ca295a98-2c8e-4019-9e91-81240d849c6b | ingest_bundle | queued | 0 | 3 | None | None | None | None

PS C:\ATS> C:/ATS/.venv/Scripts/python.exe final_state.py
SELECT id,status FROM research_runs WHERE id='55555555-5555-5555-5555-555555555555';
55555555-5555-5555-5555-555555555555 | failed

SELECT id,status,attempts,max_attempts,retry_at,last_error FROM research_jobs WHERE run_id='55555555-5555-5555-5555-555555555555' ORDER BY created_at DESC LIMIT 1;
ca295a98-2c8e-4019-9e91-81240d849c6b | queued | 2 | 3 | 2025-12-29 04:57:13.776776+00:00 | Job ca295a98-2c8e-4019-9e91-81240d849c6b failed: no_company_research_run_id: Phase 2 ingestion requi

SELECT COUNT(*) FROM company_prospects WHERE tenant_id='44444444-4444-4444-4444-444444444444';
0
```

## 3) Upload Validation Test
```
PS C:\ATS> C:/ATS/.venv/Scripts/python.exe http_validation_test.py
HTTP Error: All connection attempts failed
```

## 4) Retry Semantics Proof
```
PS C:\ATS> C:/ATS/.venv/Scripts/python.exe test_retry_semantics.py
Initial state: status=queued, attempts=0, max_attempts=3, retry_at=None

Job f943ce6b-b4e4-48d0-a924-fb1dbb0d4437 failed (attempt 1/3), will retry in 30s at 2025-12-29 08:52:24.556607: Simulated failure 1

After attempt 1: status=queued, attempts=1, retry_at=2025-12-29 04:52:24.556607+00:00, error=Simulated failure 1...

Job f943ce6b-b4e4-48d0-a924-fb1dbb0d4437 failed (attempt 2/3), will retry in 60s at 2025-12-29 08:52:54.561125: Simulated failure 2

After attempt 2: status=queued, attempts=2, retry_at=2025-12-29 04:52:54.561125+00:00, error=Simulated failure 2...

Job f943ce6b-b4e4-48d0-a924-fb1dbb0d4437 permanently failed after 3 attempts: Simulated failure 3

After attempt 3: status=failed, attempts=3, retry_at=None, error=Simulated failure 3...

✅ Job correctly marked as permanently failed

UPDATE research_jobs SET attempts=$1::INTEGER, retry_at=$2::TIMESTAMP WITH TIME ZONE, locked_at=$3::TIMESTAMP WITH TIME ZONE, locked_by=$4::VARCHAR, last_error=$5::VARCHAR, updated_at=now() WHERE research_jobs.id = $6::UUID
[parameters: (1, datetime.datetime(2025, 12, 29, 8, 52, 24, 556607), None, None, 'Simulated failure 1', UUID('f943ce6b-b4e4-48d0-a924-fb1dbb0d4437'))]

UPDATE research_jobs SET attempts=$1::INTEGER, retry_at=$2::TIMESTAMP WITH TIME ZONE, last_error=$3::VARCHAR, updated_at=now() WHERE research_jobs.id = $4::UUID
[parameters: (2, datetime.datetime(2025, 12, 29, 8, 52, 54, 561125), 'Simulated failure 2', UUID('f943ce6b-b4e4-48d0-a924-fb1dbb0d4437'))]

UPDATE research_jobs SET status=$1::VARCHAR, attempts=$2::INTEGER, retry_at=$3::TIMESTAMP WITH TIME ZONE, last_error=$4::VARCHAR, updated_at=now() WHERE research_jobs.id = $5::UUID
[parameters: ('failed', 3, None, 'Simulated failure 3', UUID('f943ce6b-b4e4-48d0-a924-fb1dbb0d4437'))]
```

## 5) Worker Logs - Real Retry Progression  
```
PS C:\ATS> C:/ATS/.venv/Scripts/python.exe run_worker_once.py
2025-12-29 12:56:06,842 - app.services.durable_job_service - WARNING - Job f943ce6b-b4e4-48d0-a924-fb1dbb0d4437 failed (attempt 2/3), will retry in 60s at 2025-12-29 08:57:06.842078: Job f943ce6b-b4e4-48d0-a924-fb1dbb0d4437 failed: No stored bundle found

2025-12-29 12:56:13,776 - app.services.durable_job_service - WARNING - Job ca295a98-2c8e-4019-9e91-81240d849c6b failed (attempt 2/3), will retry in 60s at 2025-12-29 08:57:13.776776: Job ca295a98-2c8e-4019-9e91-81240d849c6b failed: no_company_research_run_id: Phase 2 ingestion requires company_research_run_id

SELECT research_jobs.run_id, research_jobs.job_type, research_jobs.status, research_jobs.attempts, research_jobs.max_attempts, research_jobs.retry_at, research_jobs.locked_at, research_jobs.locked_by, research_jobs.last_error, research_jobs.payload_json, research_jobs.id, research_jobs.tenant_id, research_jobs.created_at, research_jobs.updated_at FROM research_jobs
WHERE research_jobs.status = $1::VARCHAR AND (research_jobs.retry_at IS NULL OR research_jobs.retry_at <= $2::TIMESTAMP WITH TIME ZONE) OR research_jobs.status = $3::VARCHAR AND research_jobs.locked_at < $4::TIMESTAMP WITH TIME ZONE ORDER BY research_jobs.created_at LIMIT $5::INTEGER FOR UPDATE SKIP LOCKED
[parameters: ('queued', datetime.datetime(2025, 12, 29, 8, 56, 6, 571489), 'running', datetime.datetime(2025, 12, 29, 8, 26, 6, 571489), 1)]
```
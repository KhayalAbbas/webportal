# Phase 3.4 Raw Proof Outputs

## 1) Migration Applied Proof

### alembic current
```
c06d212c49af (head)
c06d212c49af (head)
```

### research_jobs table structure
```
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

## 2) Upload-time Validation Proof

### Invalid Bundle Upload Test


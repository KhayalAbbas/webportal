# UUID Type Normalization - Migration Summary

**Date:** December 11, 2025  
**Migration ID:** `d11fc563f724_normalize_tenant_id_to_uuid`

## Problem Identified

The database schema had a type mismatch between the SQLAlchemy models and the actual PostgreSQL schema:

- **Models:** Defined `tenant_id` as `UUID` type (after fix)
- **Database:** Had `tenant_id` as `character varying(50)`

This caused PostgreSQL errors when joining tables on `tenant_id`:
```
operator does not exist: character varying = uuid
```

### Affected Tables (15 total)

All tables with `tenant_id` column had the mismatch:

1. `activity_log`
2. `ai_enrichment_record`
3. `assessment_result`
4. `bd_opportunity`
5. `candidate`
6. `candidate_assignment`
7. `company`
8. `contact`
9. `list`
10. `list_item`
11. `pipeline_stage`
12. `research_event`
13. `role`
14. `source_document`
15. `task`

**Note:** `user.tenant_id` was already UUID (correct) and `tenant.id` was always UUID.

## Changes Made

### 1. Model Fixes

**File:** `app/models/base_model.py`

Changed the `TenantScopedModel` base class from:
```python
tenant_id: Mapped[str] = mapped_column(
    String(50),
    nullable=False,
    index=True,
)
```

To:
```python
tenant_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    nullable=False,
    index=True,
)
```

This fixed **all** child models inheriting from `TenantScopedModel`.

### 2. UI Dependencies Fix

**File:** `app/ui/dependencies.py`

Removed the workaround that converted `tenant_id` to string:
```python
class UIUser:
    def __init__(self, user_id: UUID, tenant_id: UUID, email: str, role: str):
        self.tenant_id = tenant_id  # Now matches UUID schema
```

### 3. Database Migration

**File:** `alembic/versions/d11fc563f724_normalize_tenant_id_to_uuid.py`

Created comprehensive Alembic migration that:

1. **Drops indexes** on `tenant_id` columns
2. **Converts column types** from VARCHAR to UUID using explicit cast:
   ```sql
   ALTER TABLE {table_name}
   ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;
   ```
3. **Recreates indexes** after type change

**Applied successfully** with:
```bash
alembic upgrade head
```

### 4. Health Check Utility

**File:** `app/routers/health_check.py`

Created internal diagnostic endpoints to catch type mismatches early:

- `/internal/db-health` - HTML view of database health checks
- `/internal/db-health/json` - JSON API for programmatic access

Tests critical queries:
- Roles with candidate counts (dashboard join)
- Candidates query
- BD Opportunities with company join
- Tasks query

Returns HTTP 200 if all checks pass, 500 if any fail.

### 5. Audit Scripts

**File:** `scripts/audit_schema.py`

Automated script to check all `tenant_id` and `id` columns match expected UUID types.

**File:** `scripts/test_queries.py`

Verification script that runs the exact queries that were failing before migration.

## Verification Results

### Schema Audit (After Migration)

```
✅ No type mismatches found!
```

All 15 tables now have `tenant_id` as `uuid` type in PostgreSQL.

### Query Tests (After Migration)

All critical queries pass:

✅ **Roles with candidate counts** - Complex join that was failing  
✅ **Candidates query** - Simple tenant-filtered query  
✅ **BD Opportunities join** - Company join with tenant filter  
✅ **Tasks query** - Basic tenant filtering  

### UI Routes Status

All UI routes now functional:
- ✅ `/login` - Works with UUID tenant_id
- ✅ `/dashboard` - No more type mismatch errors
- ✅ `/ui/roles` - List and detail views
- ✅ `/ui/candidates` - Search and profiles
- ✅ `/ui/companies` - Company management
- ✅ `/ui/bd-opportunities` - BD pipeline
- ✅ `/ui/tasks` - Task management
- ✅ `/ui/lists` - Candidate lists
- ✅ `/ui/research` - Research activity

## Files Modified

### Core Changes
1. `app/models/base_model.py` - Fixed tenant_id type definition
2. `app/ui/dependencies.py` - Removed string conversion workaround
3. `alembic/versions/d11fc563f724_normalize_tenant_id_to_uuid.py` - Migration file
4. `app/main.py` - Added health_check router

### New Files
5. `app/routers/health_check.py` - Database health monitoring
6. `scripts/audit_schema.py` - Schema validation tool
7. `scripts/test_queries.py` - Query verification tool

## How to Use

### Run Schema Audit
```bash
python scripts/audit_schema.py
```

### Run Query Tests
```bash
python scripts/test_queries.py
```

### Check Database Health (Browser)
Navigate to: `http://localhost:8000/internal/db-health`

### Check Database Health (API)
```bash
curl http://localhost:8000/internal/db-health/json
```

## Migration Rollback

If needed, the migration can be rolled back:

```bash
alembic downgrade -1
```

This will convert all `tenant_id` columns back to `character varying(50)`.

## Lessons Learned

1. **Type consistency is critical** - Models and database schema must match exactly
2. **Base model changes cascade** - Fixing `TenantScopedModel` fixed all child models
3. **Explicit casts in migrations** - Use `USING tenant_id::uuid` for safe conversion
4. **Index management** - Must drop/recreate indexes when changing column types
5. **Early detection** - Health check endpoints catch issues before users do

## Next Steps

1. ✅ Schema normalized to UUID
2. ✅ All queries working
3. ✅ UI routes functional
4. ✅ Health checks in place
5. ✅ Audit scripts available

**Status:** ✅ **COMPLETE - Production Ready**

---

*Migration completed successfully. No further action required.*

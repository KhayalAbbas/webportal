# Phase 10.6 Release Notes

## What changed
- Added export pack registry table with relative storage pointers under EXPORT_PACK_STORAGE_ROOT and alembic migration b6f20f1d5a7c applied.
- Repository/service now register export packs on download, validate pointers (no traversal/drive), and reuse file hashes for deterministic registry entries.
- API supports listing export packs per run and downloading by export id; UI run detail shows export history table with download links.
- Proof exercises dual exports, verifies registry ordering (created_at desc, id desc), matches hashes via download-by-id, and captures OpenAPI/port/alembic head evidence.

## How to run the Phase 10.6 proof
```powershell
cd C:\ATS
. ./scripts/runbook/LOCAL_COMMANDS.ps1
# Ensure API is reachable (ALLOW_START_API=1 if needed for runbook health/openapi)
& $env:ATS_PYTHON_EXE scripts/proofs/phase_10_6_export_pack_registry.py
```

## Key artifacts
- phase_10_6_preflight.txt (port, health, openapi, alembic, git)
- phase_10_6_proof.txt / phase_10_6_proof_console.txt (dual export, registry ordering, hash checks)
- phase_10_6_export_hashes.txt / phase_10_6_export_file_list.txt / phase_10_6_db_excerpt.sql.txt
- phase_10_6_export_first.zip / phase_10_6_export_second.zip (registry content snapshots)
- phase_10_6_openapi_after.json / phase_10_6_openapi_after_excerpt.txt / phase_10_6_port_check.txt
- phase_10_6_alembic_upgrade.txt / phase_10_6_alembic_current.txt / phase_10_6_alembic_heads.txt
- phase_10_6_ui_html_excerpt.html
- phase_10_6_git_status_before_commit.txt / phase_10_6_git_diff_stat.txt / phase_10_6_git_log_before_commit.txt / phase_10_6_master_ahead_behind.txt

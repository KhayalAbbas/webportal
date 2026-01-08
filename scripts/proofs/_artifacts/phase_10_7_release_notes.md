# Phase 10.7 — Export pack negative hardening

## Changes
- Harmonized tenant access errors to structured codes (`TENANT_HEADER_REQUIRED`, `TENANT_FORBIDDEN`).
- Added deterministic negative proof for export-pack list/download authz and traversal rejection using ASGITransport and Phase 7.10 fixtures.
- Captured traversal guard evidence by injecting an `../evil.zip` pointer and confirming 404 envelope with export_id echo.

## Tests
- scripts/proofs/phase_10_7_export_pack_negative.py (ASGITransport)
- Preflight: port 8000 reachable, health 200, openapi 200, alembic head b6f20f1d5a7c, git clean recorded in artifact.

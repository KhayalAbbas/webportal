# Phase 10.4 Release Notes

## Highlights
- Added market-test orchestration endpoint to drive seed discovery, review gate, acquire/extract enqueue, dual engine executive discovery, compare snapshot, promotion, and export pack for a run.
- Deterministic offline proof exercises two passes (idempotent) with fixture server content, export hash/file list capture, and job status snapshots.
- Seed-list evidence kind aligned to provider schema and test client now overrides auth dependency for in-process ASGI proof runs.

## Proof Artifacts
- scripts/proofs/phase_10_4_market_test_orchestration_proof.py
- scripts/proofs/_artifacts/phase_10_4_preflight.txt
- scripts/proofs/_artifacts/phase_10_4_discovery_notes.txt
- scripts/proofs/_artifacts/phase_10_4_design_notes.txt
- scripts/proofs/_artifacts/phase_10_4_first_call.json
- scripts/proofs/_artifacts/phase_10_4_second_call.json
- scripts/proofs/_artifacts/phase_10_4_compare_snapshot.json
- scripts/proofs/_artifacts/phase_10_4_job_statuses.json
- scripts/proofs/_artifacts/phase_10_4_promote.json
- scripts/proofs/_artifacts/phase_10_4_export.zip
- scripts/proofs/_artifacts/phase_10_4_export_hash.txt
- scripts/proofs/_artifacts/phase_10_4_export_file_list.txt
- scripts/proofs/_artifacts/phase_10_4_db_excerpt.txt
- scripts/proofs/_artifacts/phase_10_4_proof.txt
- scripts/proofs/_artifacts/phase_10_4_proof_console.txt
- scripts/proofs/_artifacts/phase_10_4_openapi_before.json
- scripts/proofs/_artifacts/phase_10_4_openapi_after.json
- scripts/proofs/_artifacts/phase_10_4_openapi_after_excerpt.txt

## Notes
- Market-test proof runs via ASGI transport with dependency override for `verify_user_tenant_access` and tenant header set; no external services required.
- Export pack hash and file list are captured from the zip response for reproducibility.
- Seed evidence uses allowed evidence kind `other` to satisfy `SeedListProviderRequest` validation.

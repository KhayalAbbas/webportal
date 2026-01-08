# Phase 10.4 Release Notes

## Highlights
- Added market-test orchestration endpoint to drive seed discovery, review gate, acquire/extract enqueue, dual engine executive discovery, compare snapshot, promotion, and export pack for a run.
- Deterministic offline proof exercises two passes (idempotent second call) with fixture server content; export hash/file list captured and stable (`28ceff230c9c8fa0f4b44f26bc54ff5607f7580529363102a0faac483c8e9b6a`).
- Seed evidence kind aligned to provider schema; proof client overrides auth dependency and sets tenant header for in-process ASGI run.

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
- scripts/proofs/_artifacts/phase_10_4_git_status_before_commit.txt
- scripts/proofs/_artifacts/phase_10_4_git_diff_stat.txt
- scripts/proofs/_artifacts/phase_10_4_git_log_before_commit.txt

## Notes
- Market-test proof runs via ASGI transport with dependency override for `verify_user_tenant_access` and tenant header set; no external services required.
- Export pack hash and file list are captured from the zip response for reproducibility; second call reuses discovery/jobs without duplicates.
- OpenAPI after/excerpt includes `/company-research/runs/{run_id}/market-test` request/response schemas for client integration.

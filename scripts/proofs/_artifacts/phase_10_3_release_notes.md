# Phase 10.3 Release Notes

## Highlights
- Added job cancel + retry endpoints with persisted cancel flags and resettable attempts.
- Introduced lease recovery endpoint to reclaim stale acquire_extract_async jobs by worker-id and cutoff.
- Deterministic offline proof covers cancel, retry after failure, and stale lease reclamation.

## Proof Artifacts
- scripts/proofs/phase_10_3_job_controls_proof.py
- scripts/proofs/_artifacts/phase_10_3_proof.txt
- scripts/proofs/_artifacts/phase_10_3_proof_console.txt
- scripts/proofs/_artifacts/phase_10_3_cancel.json
- scripts/proofs/_artifacts/phase_10_3_status_cancelled.json
- scripts/proofs/_artifacts/phase_10_3_retry.json
- scripts/proofs/_artifacts/phase_10_3_status_retried_succeeded.json
- scripts/proofs/_artifacts/phase_10_3_status_failed.json
- scripts/proofs/_artifacts/phase_10_3_enqueue_reclaim.json
- scripts/proofs/_artifacts/phase_10_3_status_reclaimed.json
- scripts/proofs/_artifacts/phase_10_3_db_excerpt.txt
- scripts/proofs/_artifacts/phase_10_3_openapi_after.json
- scripts/proofs/_artifacts/phase_10_3_openapi_after_excerpt.txt

## Notes
- execute_acquire_extract_job is idempotent and records failures; proof swallows expected exceptions to keep runs deterministic.
- Retry endpoint supports reset_attempts to zero attempt_count before requeue.
- Lease recovery bypasses stale locks and records recovery metadata per job.

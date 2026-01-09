# Phase 10.12 Release Notes

## Scope
- Golden end-to-end proof for executive discovery and pipeline export/evidence determinism.
- Validate review gate enforcement, exec discovery gating, and deterministic export/bundle outputs for the signed-off run.
- Capture post-run artifacts (pipeline snapshot, DB excerpt, OpenAPI after) for release sign-off.

## Changes
- No new product features; updated the golden proof harness to align with the live schema (use `ai_enrichment_record`, drop legacy `provenance`/`research_source_documents` queries, handle nested exec discovery error envelope).
- Captured stable export pack and evidence bundle artifacts for run `8039c823-f280-4125-8ccc-688063dd890c`:
  - Export pack SHA `41a340b4e3dfb75aa7cd3e2af2c8bc4f50f02d52da8fd14ddc95f68f7a54709b` (size 5209, pointer `company_research/5f5b7b6b-2058-49a2-8550-82b5573c191a/runs/8039c823-f280-4125-8ccc-688063dd890c/export_08696d5d-09ee-4ecf-bf2c-7b9ebc0af2dd.zip`).
  - Evidence bundle SHA `bb3396b79c3790f9563ad6749d1c5d188003e76baae30a79ccfb1b958efe2cc3` (size 2807).
- Recorded OpenAPI snapshot after the run and captured manifest excerpts/bundle listings for release packaging.

## Proof
- Script: `scripts/proofs/phase_10_12_golden_run.py` (deterministic, ASGITransport style).
- Artifacts: `phase_10_12_preflight.txt`, `phase_10_12_proof.txt`, `phase_10_12_proof_console.txt`, `phase_10_12_pipeline_snapshot.json`, `phase_10_12_db_excerpt.sql.txt`, `phase_10_12_export_hashes.txt`, `phase_10_12_export_file_list.txt`, `phase_10_12_bundle_hashes.txt`, `phase_10_12_bundle_file_list.txt`, `phase_10_12_manifest_excerpt.json`, `phase_10_12_openapi_after.json`, `phase_10_12_openapi_after_excerpt.txt`.
- Key assertions: discovery/acquire/extract produced prospects; review gate enforcement; exec discovery blocked for unaccepted and succeeds for accepted prospects; deterministic export pack and evidence bundle hashes; pipeline snapshot + DB excerpt captured.

## Notes
- Run tenant `5f5b7b6b-2058-49a2-8550-82b5573c191a`, run id `8039c823-f280-4125-8ccc-688063dd890c`.
- Export/evidence bundle hashes and file lists are stable across reruns per proof console.
- Release bundle will include all `phase_10_12_*` artifacts for reproducibility.

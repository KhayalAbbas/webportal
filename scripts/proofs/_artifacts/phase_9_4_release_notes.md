# Phase 9.4 Release Notes

## Summary
- Added external LLM (Grok-style) discovery ingest endpoint at `/company-research/runs/{run_id}/discovery/external-llm/ingest` with structured error envelope and idempotent storage.
- Extended schemas with `ExternalLLMDiscoveryIngestRequest/Response` including reused flags and ingest counts; service maps Grok payloads into the existing discovery ingestion pipeline.
- Proof harness demonstrates two-pass idempotency (reused on identical payload), stable hashes, single enrichment, and evidence-first URL capture.

## API
- **POST** `/company-research/runs/{run_id}/discovery/external-llm/ingest`
  - Request: provider, request_id (optional), prompt/prompt_ref (optional), response_json, suggested_companies (name, website_url, evidence_urls, notes/provenance), optional suggested_urls/meta.
  - Response: source_document_id, enrichment_record_id, content_hash/input_scope_hash, companies_upserted, urls_added, evidence_links_added, reused + reused_reason.

## Proof / Verification
- Script: `scripts/proofs/phase_9_4_external_llm_discovery_ingest_proof.py` (offline, AsyncClient with auth override).
- Artifacts: `phase_9_4_proof.txt`, `phase_9_4_proof_console.txt`, `phase_9_4_first_call.json`, `phase_9_4_second_call.json`, `phase_9_4_db_excerpt.txt`, `phase_9_4_openapi_after.json`, `phase_9_4_openapi_after_excerpt.txt`.
- Result: PASS — second call reused source/enrichment/content_hash; counts stable (companies_upserted=2, urls_added=3, evidence_links_added=4); DB excerpt shows 1 llm_json source, 1 enrichment, 3 URL sources (shared URL reused), 4 evidence rows.

## Notes
- Evidence labels are index-suffixed when provenance is present to preserve multiple evidence rows per company.
- Structured errors via `raise_app_error` for locked/invalid/run-not-found cases.

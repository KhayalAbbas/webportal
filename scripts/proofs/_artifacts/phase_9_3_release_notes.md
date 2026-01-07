# Phase 9.3 Release Notes

## Highlights
- Added `google_search` discovery provider using Google Custom Search JSON API shape with injectable HTTP layer and fixture support.
- Persisted provider envelopes as SourceDocuments (redacted request metadata + response) to satisfy evidence-first auditing.
- Added config keys `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX` with structured error handling when unset.
- Offline deterministic proof harness uses a local CSE fixture, asserts 2-pass idempotency, and verifies envelope + enrichment reuse.

## Artifacts
- Preflight and OpenAPI snapshots (before/after) under scripts/proofs/_artifacts.
- Proof outputs: phase_9_3_proof.txt, console, first/second calls, DB excerpt, OpenAPI after excerpt.
- Fixture: scripts/proofs/fixtures/phase_9_3_google_cse_fixture.json (offline deterministic payload).

## Notes
- Prospects and evidence are attributed to `google_search`; URL candidates dedupe on normalized URLs.
- AI enrichment `input_scope_hash` matches discovery payload content_hash for stable reuse.
- Envelope SourceDocument is linked to the discovery source via meta.envelope_source_id for traceability.

# Phase 9.5: Company review gate + exec_search toggle + accepted-only eligibility enforcement

## Scope
- Enforce exec discovery eligibility only when prospects are accepted and exec_search_enabled=true.
- Ensure hold/reject flips exec_search_enabled to false.
- Keep exec discovery blocked before accept/enable and idempotent on second pass.

## Proof Coverage
- Deterministic proof script: scripts/proofs/phase_9_5_company_review_gate_proof.py
- Eligibility before accept/enable: empty, exec discovery blocked.
- After accept+enable: eligibility includes only accepted+enabled prospect; exec discovery runs internal+external.
- Hold/reject: exec_search_enabled forced false; eligibility excludes.
- Second pass: idempotent (no new changes).

## Artifacts
- Preflight, OpenAPI before/after + excerpt, proof outputs, API captures, DB excerpt, git evidence, commit/tag/push outputs under scripts/proofs/_artifacts/phase_9_5_*.

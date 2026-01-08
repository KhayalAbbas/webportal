# Phase 10.5 Release Notes

## What changed
- Hardened VERIFY_RUNBOOK.ps1: self-sources runbook, validates required paths/commands, uses basic parsing, and captures health/openapi snapshots.
- Deterministic tenant/user/setup for Phase 10.5 proof with fixed tenant UUID and stable export hash validation.
- Captured fresh OpenAPI (before/after), proof console, and run detail HTML.
- Tagging hygiene: canonical tag is `phase_10_5_signed_off_v4` at clean master (no force); `phase_10_5_signed_off` was forced, `phase_10_5_signed_off_v2` was superseded, and `phase_10_5_signed_off_v3` was replaced after cleaning the working tree.

## How to run the verifier
```powershell
./scripts/runbook/VERIFY_RUNBOOK.ps1
```

## How to run the Phase 10.5 proof
```powershell
cd C:\ATS
. ./scripts/runbook/LOCAL_COMMANDS.ps1
$env:ALLOW_START_API="1"
& $env:ATS_PYTHON_EXE scripts/proofs/phase_10_5_silver_arrow_market_test_ui.py
```

## Key artifacts
- phase_10_5_preflight.txt
- phase_10_5_proof.txt (PASS footer, stable export hash)
- phase_10_5_proof_console.txt
- phase_10_5_openapi_before.json
- phase_10_5_openapi_after.json
- phase_10_5_openapi_after_excerpt.txt
- phase_10_5_export_hashes.txt
- phase_10_5_run_detail.html
- phase_10_5_runbook_excerpt.txt (redacted)
- runbook_verify_log.txt / runbook_verify_openapi.json / runbook_verify_health.txt
- Tag artifacts (v4 canonical): phase_10_5_git_status_pre_v4.txt, phase_10_5_git_diff_stat_pre_v4.txt, phase_10_5_git_log_pre_v4.txt, phase_10_5_tag_v4.txt, phase_10_5_push_v4.txt, phase_10_5_git_after_v4.txt, phase_10_5_git_status_clean_master.txt
- Superseded tag evidence retained: phase_10_5_git_status_pre_v3.txt, phase_10_5_git_log_pre_v3.txt, phase_10_5_tag_v3.txt, phase_10_5_push_v3.txt, phase_10_5_git_after_v3.txt, phase_10_5_git_status_final.txt

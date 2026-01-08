# Local Runbook for ATS proofs

This folder stores the single source of truth for local commands and ports.

- Edit `LOCAL_COMMANDS.ps1` whenever the API base URL, port, or tool paths change.
- Always dot-source it before running proofs or preflights so environment variables are set:
  
  ```powershell
  . scripts/runbook/LOCAL_COMMANDS.ps1
  ```

Variables defined (with safe defaults):
- `$ATS_API_BASE_URL`
- `$ATS_PYTHON_EXE`
- `$ATS_ALEMBIC_EXE`
- `$ATS_GIT_EXE`
- `$ATS_START_API_CMD`

If you override any of these locally, set the corresponding environment variable and rerun the runbook. Commit changes to `LOCAL_COMMANDS.ps1` when the canonical local setup changes.

## Prepare your local runbook

1) Copy the template once per machine:

```powershell
Copy-Item scripts/runbook/LOCAL_COMMANDS.template.ps1 scripts/runbook/LOCAL_COMMANDS.ps1
```

2) Edit `scripts/runbook/LOCAL_COMMANDS.ps1` with your local paths/ports. This file stays untracked; the template is the committed SSOT.

3) Verify the runbook from repo root:

```powershell
./scripts/runbook/VERIFY_RUNBOOK.ps1
```

Artifacts go to `scripts/proofs/_artifacts` (log, redacted runbook excerpt, health response, OpenAPI JSON, and server console if it had to start the API).

## Run Phase 10.5 proof

From the repo root run:

```powershell
cd C:\ATS
. ./scripts/runbook/LOCAL_COMMANDS.ps1
$env:ALLOW_START_API="1"
& $env:ATS_PYTHON_EXE scripts/proofs/phase_10_5_silver_arrow_market_test_ui.py
```

## Tagging hygiene
- Never force-push signoff tags. If a tag already exists remotely, create a new tag name (e.g., `_v2`) or bump the phase tag.

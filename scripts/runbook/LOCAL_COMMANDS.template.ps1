# LOCAL runbook template (commit this file)
# Copy to LOCAL_COMMANDS.ps1 and adjust for your machine.
# Do not commit LOCAL_COMMANDS.ps1 (per .gitignore).

# API base URL (default local dev)
$ATS_API_BASE_URL = $env:ATS_API_BASE_URL
if ([string]::IsNullOrWhiteSpace($ATS_API_BASE_URL)) {
    $ATS_API_BASE_URL = "http://127.0.0.1:8000"
}

# Tool paths (override via environment if desired)
$ATS_PYTHON_EXE = $env:ATS_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($ATS_PYTHON_EXE)) {
    $ATS_PYTHON_EXE = "C:/ATS/.venv/Scripts/python.exe"
}

$ATS_ALEMBIC_EXE = $env:ATS_ALEMBIC_EXE
if ([string]::IsNullOrWhiteSpace($ATS_ALEMBIC_EXE)) {
    $ATS_ALEMBIC_EXE = "C:/ATS/.venv/Scripts/alembic.exe"
}

$ATS_GIT_EXE = $env:ATS_GIT_EXE
if ([string]::IsNullOrWhiteSpace($ATS_GIT_EXE)) {
    $ATS_GIT_EXE = "C:/Program Files/Git/bin/git.exe"
}

# Canonical command to start the API locally
$ATS_START_API_CMD = $env:ATS_START_API_CMD
if ([string]::IsNullOrWhiteSpace($ATS_START_API_CMD)) {
    $ATS_START_API_CMD = "C:/ATS/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
}

# Export to environment so child processes can consume
$env:ATS_API_BASE_URL = $ATS_API_BASE_URL
$env:ATS_PYTHON_EXE = $ATS_PYTHON_EXE
$env:ATS_ALEMBIC_EXE = $ATS_ALEMBIC_EXE
$env:ATS_GIT_EXE = $ATS_GIT_EXE
$env:ATS_START_API_CMD = $ATS_START_API_CMD

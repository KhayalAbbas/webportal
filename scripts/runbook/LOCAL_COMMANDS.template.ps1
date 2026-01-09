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

# External discovery/search providers (Phase 11.1)
$ATS_EXTERNAL_DISCOVERY_ENABLED = $env:ATS_EXTERNAL_DISCOVERY_ENABLED
if ([string]::IsNullOrWhiteSpace($ATS_EXTERNAL_DISCOVERY_ENABLED)) {
    $ATS_EXTERNAL_DISCOVERY_ENABLED = "0"
}

$ATS_MOCK_EXTERNAL_PROVIDERS = $env:ATS_MOCK_EXTERNAL_PROVIDERS
if ([string]::IsNullOrWhiteSpace($ATS_MOCK_EXTERNAL_PROVIDERS)) {
    $ATS_MOCK_EXTERNAL_PROVIDERS = "0"
}

# Encrypted secrets master key (Phase 11.3)
$ATS_SECRETS_MASTER_KEY = $env:ATS_SECRETS_MASTER_KEY
if ([string]::IsNullOrWhiteSpace($ATS_SECRETS_MASTER_KEY)) {
    $ATS_SECRETS_MASTER_KEY = ""
}

$ATS_SECRETS_KEY_VERSION = $env:ATS_SECRETS_KEY_VERSION
if ([string]::IsNullOrWhiteSpace($ATS_SECRETS_KEY_VERSION)) {
    $ATS_SECRETS_KEY_VERSION = "1"
}

$ATS_SEARCH_CACHE_TTL_SECONDS = $env:ATS_SEARCH_CACHE_TTL_SECONDS
if ([string]::IsNullOrWhiteSpace($ATS_SEARCH_CACHE_TTL_SECONDS)) {
    $ATS_SEARCH_CACHE_TTL_SECONDS = "604800"
}

$XAI_API_KEY = $env:XAI_API_KEY
$XAI_MODEL = $env:XAI_MODEL
if ([string]::IsNullOrWhiteSpace($XAI_MODEL)) {
    $XAI_MODEL = "grok-2"
}

$GOOGLE_CSE_API_KEY = $env:GOOGLE_CSE_API_KEY
$GOOGLE_CSE_CX = $env:GOOGLE_CSE_CX

# Export to environment so child processes can consume
$env:ATS_API_BASE_URL = $ATS_API_BASE_URL
$env:ATS_PYTHON_EXE = $ATS_PYTHON_EXE
$env:ATS_ALEMBIC_EXE = $ATS_ALEMBIC_EXE
$env:ATS_GIT_EXE = $ATS_GIT_EXE
$env:ATS_START_API_CMD = $ATS_START_API_CMD
$env:ATS_EXTERNAL_DISCOVERY_ENABLED = $ATS_EXTERNAL_DISCOVERY_ENABLED
$env:ATS_MOCK_EXTERNAL_PROVIDERS = $ATS_MOCK_EXTERNAL_PROVIDERS
$env:ATS_SECRETS_MASTER_KEY = $ATS_SECRETS_MASTER_KEY
$env:ATS_SECRETS_KEY_VERSION = $ATS_SECRETS_KEY_VERSION
$env:ATS_SEARCH_CACHE_TTL_SECONDS = $ATS_SEARCH_CACHE_TTL_SECONDS
$env:XAI_API_KEY = $XAI_API_KEY
$env:XAI_MODEL = $XAI_MODEL
$env:GOOGLE_CSE_API_KEY = $GOOGLE_CSE_API_KEY
$env:GOOGLE_CSE_CX = $GOOGLE_CSE_CX

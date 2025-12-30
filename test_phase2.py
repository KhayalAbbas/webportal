"""
Test Phase 2 AI Proposal Ingestion
"""
import json
import os
import requests
import pytest

if os.environ.get('RUN_SERVER_TESTS') != '1':
    pytest.skip('Server not running; set RUN_SERVER_TESTS=1 to enable HTTP API tests', allow_module_level=True)

# Load sample proposal
with open('sample_ai_proposal.json', 'r') as f:
    proposal_json = f.read()

# Get the run ID from the database or create a test run
# For this test, we'll need to manually set the run_id after logging in

BASE_URL = "http://localhost:8000"

# Test validation endpoint
print("=" * 60)
print("Testing Phase 2 AI Proposal Validation")
print("=" * 60)

# Note: You need to be logged in and have a valid run_id
# This script demonstrates the API structure
# In practice, you'll use the UI which handles authentication

run_id = "YOUR_RUN_ID_HERE"  # Replace with actual run ID from UI

# Validation request
validation_response = requests.post(
    f"{BASE_URL}/ui/company-research/runs/{run_id}/validate-proposal",
    data={"proposal_json": proposal_json}
)

print(f"\nValidation Response: {validation_response.status_code}")
if validation_response.status_code == 200:
    result = validation_response.json()
    print(json.dumps(result, indent=2))
else:
    print(validation_response.text)

print("\n" + "=" * 60)
print("Instructions for manual testing:")
print("=" * 60)
print("1. Open browser to http://localhost:8000")
print("2. Log in with your credentials")
print("3. Create a new research run or open existing one")
print("4. Scroll to 'Phase 2: Ingest AI-Generated Proposal'")
print("5. Paste the content of sample_ai_proposal.json")
print("6. Click 'Validate' to check for errors")
print("7. Click 'Ingest Proposal' to import the data")
print("8. Verify the table shows 5 UAE banks with metrics and AI ranks")
print("9. Try sorting by 'AI Rank' and 'Primary Metric'")
print("\nExpected results:")
print("- 5 companies: FAB, Emirates NBD, ADCB, DIB, Mashreq")
print("- AI Ranks: 1-5")
print("- Primary Metric: Total Assets in AED/USD")
print("- AI Scores: 0.92-0.98")

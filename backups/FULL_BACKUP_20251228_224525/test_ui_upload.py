#!/usr/bin/env python3
"""Test script for Phase 3 UI upload functionality"""
import requests
import json

BASE_URL = "http://127.0.0.1:8005"

def test_success():
    """Test successful upload"""
    print("=== SUCCESS TEST ===")
    
    # Login
    session = requests.Session()
    login_resp = session.post(f"{BASE_URL}/ui/auth/login", data={
        'email': 'admin@test.com',
        'password': 'admin123'
    })
    print(f"Login: {login_resp.status_code}")
    
    # Upload valid bundle
    with open("fresh_bundle.json", "rb") as f:
        upload_resp = session.post(f"{BASE_URL}/ui/research/upload", 
            data={'objective': 'UI Success Test Bundle'},
            files={'bundle_file': ('fresh_bundle.json', f, 'application/json')}
        )
    print(f"Upload: {upload_resp.status_code}")
    
    # Extract key fields from HTML
    html = upload_resp.text
    for pattern in ['Run ID:', 'Status:', 'Bundle SHA256:', 'already_accepted', 'Message:']:
        if pattern in html:
            print(f"Found: {pattern}")
    
    # Extract run_id value
    import re
    run_id_match = re.search(r'<code[^>]*>([a-f0-9-]{36})</code>', html)
    if run_id_match:
        print(f"Run ID: {run_id_match.group(1)}")
    
    return html

def test_failure():
    """Test failed upload"""
    print("\n=== FAILURE TEST ===")
    
    # Login
    session = requests.Session()
    login_resp = session.post(f"{BASE_URL}/ui/auth/login", data={
        'email': 'admin@test.com',
        'password': 'admin123'
    })
    print(f"Login: {login_resp.status_code}")
    
    # Upload invalid bundle
    with open("invalid_bundle.json", "rb") as f:
        upload_resp = session.post(f"{BASE_URL}/ui/research/upload", 
            data={'objective': 'UI Failure Test Bundle'},
            files={'bundle_file': ('invalid_bundle.json', f, 'application/json')}
        )
    print(f"Upload: {upload_resp.status_code}")
    
    # Extract error message
    html = upload_resp.text
    import re
    error_match = re.search(r'<strong>Error:</strong>\s*([^<]+)', html, re.DOTALL)
    if error_match:
        print(f"Error Message: {error_match.group(1).strip()}")
    
    return html

if __name__ == "__main__":
    test_success()
    test_failure()
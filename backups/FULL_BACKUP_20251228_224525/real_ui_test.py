#!/usr/bin/env python3
"""Real UI upload tests with actual HTML parsing"""

import os
import sys
import time
import json
import subprocess
import hashlib
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://127.0.0.1:8005"
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ats_db"

def start_server():
    """Start the FastAPI server"""
    env = os.environ.copy()
    env['DATABASE_URL'] = DATABASE_URL
    
    proc = subprocess.Popen([
        sys.executable, '-m', 'uvicorn', 'app.main:app', 
        '--host', '127.0.0.1', '--port', '8005'
    ], env=env, cwd='.')
    
    # Wait for server to start
    for i in range(15):
        try:
            resp = requests.get(f"{BASE_URL}/docs", timeout=2)
            if resp.status_code == 200:
                print(f"Server started successfully after {i+1} attempts")
                return proc
        except:
            time.sleep(1)
    
    print("Failed to start server")
    proc.terminate()
    return None

def test_login_url():
    """Find correct login URL"""
    urls_to_test = ["/login", "/ui/auth/login", "/auth/login", "/ui/login"]
    
    for url in urls_to_test:
        try:
            resp = requests.get(f"{BASE_URL}{url}", timeout=5)
            print(f"URL: {url} -> Status: {resp.status_code}")
            if resp.status_code == 200 and 'login' in resp.text.lower():
                return url
        except Exception as e:
            print(f"URL: {url} -> Error: {e}")
    
    return None

def login_and_get_session(login_url):
    """Login and return session"""
    session = requests.Session()
    
    # POST login
    login_resp = session.post(f"{BASE_URL}{login_url}", data={
        'email': 'admin@test.com',
        'password': 'admin123',
        'tenant_id': 'b3909011-8bd3-439d-a421-3b70fae124e9'
    }, timeout=10)
    
    print(f"Login POST Status: {login_resp.status_code}")
    if login_resp.history:
        print(f"Redirected to: {login_resp.url}")
    
    return session, login_resp.status_code

def extract_fields_from_html(html, save_as=None):
    """Extract upload result fields from HTML"""
    if save_as:
        with open(f"{save_as}.html", 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Saved HTML to {save_as}.html for debugging")
    
    soup = BeautifulSoup(html, 'html.parser')
    results = {}
    
    # Extract run_id - look for pattern "Run ID:" followed by code block
    run_id_pattern = r'Run ID:</strong><br>\s*<code[^>]*>([a-f0-9-]{36})</code>'
    run_id_match = re.search(run_id_pattern, html, re.DOTALL | re.IGNORECASE)
    if run_id_match:
        results['run_id'] = run_id_match.group(1)
    
    # Extract status - look for pattern "Status:" followed by span
    status_pattern = r'Status:</strong><br>\s*<span[^>]*>([^<]+)</span>'
    status_match = re.search(status_pattern, html, re.DOTALL | re.IGNORECASE)
    if status_match:
        results['status'] = status_match.group(1).strip()
    
    # Extract bundle_sha256 - look for pattern "Bundle SHA256:" followed by code block
    sha256_pattern = r'Bundle SHA256:</strong><br>\s*<code[^>]*>([a-f0-9]{64})</code>'
    sha256_match = re.search(sha256_pattern, html, re.DOTALL | re.IGNORECASE)
    if sha256_match:
        results['bundle_sha256'] = sha256_match.group(1)
    
    # Extract message - look for pattern "Message:" followed by span
    message_pattern = r'Message:</strong><br>\s*<span[^>]*>([^<]+)</span>'
    message_match = re.search(message_pattern, html, re.DOTALL | re.IGNORECASE)
    if message_match:
        results['message'] = message_match.group(1).strip()
    
    # Check for already_accepted indicator
    already_pattern = r'already accepted previously|already_accepted'
    if re.search(already_pattern, html, re.IGNORECASE):
        results['already_accepted'] = True
    else:
        results['already_accepted'] = False
    
    # Extract error - look for error sections
    error_patterns = [
        r'<strong[^>]*>Error:</strong>\s*([^<]+)',
        r'<strong[^>]*>Error Details:</strong>.*?<div[^>]*>([^<]+)</div>',
        r'background: #f5c6cb.*?>([^<]+)</div>'
    ]
    
    for pattern in error_patterns:
        error_match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if error_match:
            # Clean up the error text
            error_text = error_match.group(1).strip()
            # Remove HTML entities
            error_text = error_text.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
            results['error'] = error_text
            break
    
    return results

def create_invalid_bundle():
    """Create bundle with mismatched SHA256"""
    # Load valid bundle
    with open('fresh_bundle.json', 'r') as f:
        bundle = json.load(f)
    
    # Change content but keep old SHA256 to create mismatch
    if bundle['sources'] and len(bundle['sources']) > 0:
        # Keep the original sha256 unchanged
        original_sha256 = bundle['sources'][0]['sha256']
        # Change the content_text to something completely different
        bundle['sources'][0]['content_text'] = "This is COMPLETELY DIFFERENT content that will NOT match the original SHA256 hash at all!"
        # Ensure sha256 stays the same (this creates the mismatch)
        bundle['sources'][0]['sha256'] = original_sha256
        
        print(f"Created invalid bundle: kept sha256={original_sha256}, changed content_text")
    
    # Save invalid bundle
    with open('invalid_sha256_bundle.json', 'w') as f:
        json.dump(bundle, f, indent=2)
    
    print("Created invalid bundle with SHA256 mismatch")

def run_tests():
    """Run both success and failure tests"""
    print("=== STARTING REAL UI UPLOAD TESTS ===")
    
    # Start server
    proc = start_server()
    if not proc:
        return
    
    try:
        # Find login URL
        login_url = test_login_url()
        if not login_url:
            print("Could not find working login URL")
            return
        
        print(f"Using login URL: {login_url}")
        
        # Test 1: Success case
        print("\n=== SUCCESS TEST ===")
        session, login_status = login_and_get_session(login_url)
        
        if login_status in [200, 302]:
            with open('fresh_bundle.json', 'rb') as f:
                upload_resp = session.post(f"{BASE_URL}/ui/research/upload",
                    data={'objective': 'Real UI Test Success'},
                    files={'bundle_file': ('fresh_bundle.json', f, 'application/json')},
                    timeout=30
                )
            
            print(f"Upload Status: {upload_resp.status_code}")
            
            if upload_resp.status_code == 200:
                fields = extract_fields_from_html(upload_resp.text, save_as="success_test")
                print("SUCCESS - Extracted fields:")
                for key, value in fields.items():
                    if key == 'bundle_sha256' and value:
                        print(f"  {key}: {value[:16]}...")
                    else:
                        print(f"  {key}: {value}")
                        
                # Verify this is actually a success response
                if 'error' in fields:
                    print(f"❌ SUCCESS TEST FAILED - Got error: {fields['error'][:200]}...")
                elif 'run_id' in fields:
                    print("✅ SUCCESS TEST PASSED - Got run_id")
                else:
                    print("⚠️ SUCCESS TEST UNCLEAR - No run_id or error found")
            else:
                print(f"Upload failed with status {upload_resp.status_code}")
                print(upload_resp.text[:500])
        
        # Test 2: Failure case
        print("\n=== FAILURE TEST (SHA256 MISMATCH) ===")
        create_invalid_bundle()
        
        session2, login_status2 = login_and_get_session(login_url)
        
        if login_status2 in [200, 302]:
            with open('invalid_sha256_bundle.json', 'rb') as f:
                upload_resp2 = session2.post(f"{BASE_URL}/ui/research/upload",
                    data={'objective': 'Real UI Test Failure'},
                    files={'bundle_file': ('invalid_sha256_bundle.json', f, 'application/json')},
                    timeout=30
                )
            
            print(f"Upload Status: {upload_resp2.status_code}")
            
            if upload_resp2.status_code == 200:
                fields = extract_fields_from_html(upload_resp2.text, save_as="failure_test")
                print("FAILURE - Extracted fields:")
                for key, value in fields.items():
                    print(f"  {key}: {value}")
                
                # Verify this is actually an error response with SHA256 mismatch
                if 'error' in fields and fields['error']:
                    error_text = fields['error'].lower()
                    if 'sha256' in error_text and ('mismatch' in error_text or 'match' in error_text):
                        print("✅ FAILURE TEST PASSED - Got SHA256 mismatch error as expected")
                    else:
                        print(f"❌ FAILURE TEST FAILED - Got error but not SHA256 mismatch: {fields['error'][:200]}...")
                elif 'run_id' in fields:
                    print("❌ FAILURE TEST FAILED - Got success response instead of error!")
                    print("Full HTML saved to failure_test.html for inspection")
                else:
                    print("❌ FAILURE TEST FAILED - Unclear response, no run_id or error")
            else:
                print(f"Upload failed with status {upload_resp2.status_code}")
                print(upload_resp2.text[:500])
    
    finally:
        print("\nTerminating server...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    run_tests()
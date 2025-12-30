#!/usr/bin/env python3
"""Simple test to verify fix"""
import os
import sys
import time
import subprocess
import requests

# Start server
env = os.environ.copy()
env['DATABASE_URL'] = 'postgresql+asyncpg://postgres:postgres@localhost:5432/ats_db'

proc = subprocess.Popen([
    sys.executable, '-m', 'uvicorn', 'app.main:app', 
    '--host', '127.0.0.1', '--port', '8005'
], env=env)

# Wait for server
time.sleep(3)

try:
    # Test login
    session = requests.Session()
    login_resp = session.post('http://127.0.0.1:8005/login', data={
        'email': 'admin@test.com',
        'password': 'admin123', 
        'tenant_id': 'b3909011-8bd3-439d-a421-3b70fae124e9'
    })
    
    print(f"Login: {login_resp.status_code}")
    
    # Upload valid bundle
    with open('fresh_bundle.json', 'rb') as f:
        resp = session.post('http://127.0.0.1:8005/ui/research/upload',
            data={'objective': 'Simple Test'},
            files={'bundle_file': f}
        )
    
    print(f"Upload: {resp.status_code}")
    
    if resp.status_code == 200:
        # Check for success indicators
        html = resp.text
        if 'Upload Successful' in html:
            print("✅ SUCCESS")
        elif 'Error' in html:
            print("❌ ERROR in response")
            # Find error details
            import re
            error = re.search(r'<strong>Error:</strong>\s*([^<]+)', html)
            if error:
                print(f"Error: {error.group(1)}")
        else:
            print("? Unknown response")
            
finally:
    proc.terminate()
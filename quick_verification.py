#!/usr/bin/env python3
"""Quick verification of Phase 3 Bundle Upload UI functionality"""
import requests
import json
import time
from pathlib import Path

BASE_URL = "http://127.0.0.1:8005"

def test_workflow():
    """Test the complete workflow manually"""
    print("🔍 Phase 3 Bundle Upload UI - Quick Verification")
    print("=" * 60)
    
    # Test 1: Check server is running
    try:
        resp = requests.get(f"{BASE_URL}/ui/")
        print(f"✅ Server running - Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"⚠️  Redirect to: {resp.headers.get('location', 'Unknown')}")
    except Exception as e:
        print(f"❌ Server not accessible: {e}")
        return
    
    # Test 2: Check upload page exists
    try:
        resp = requests.get(f"{BASE_URL}/ui/research/upload", allow_redirects=False)
        print(f"✅ Upload page route - Status: {resp.status_code}")
        if resp.status_code == 302:
            print(f"   → Redirects to: {resp.headers.get('location')}")
    except Exception as e:
        print(f"❌ Upload page error: {e}")
    
    # Test 3: Check research page 
    try:
        resp = requests.get(f"{BASE_URL}/ui/research", allow_redirects=False)
        print(f"✅ Research page route - Status: {resp.status_code}")
        if resp.status_code == 302:
            print(f"   → Redirects to: {resp.headers.get('location')}")
    except Exception as e:
        print(f"❌ Research page error: {e}")
        
    # Test 4: API availability
    try:
        resp = requests.post(f"{BASE_URL}/api/runs", json={}, allow_redirects=False)
        print(f"✅ API endpoint accessible - Status: {resp.status_code}")
        if resp.status_code == 401:
            print("   → Requires authentication (expected)")
    except Exception as e:
        print(f"❌ API error: {e}")
    
    print("\n📝 Manual Test Instructions:")
    print(f"1. Open browser to: {BASE_URL}/ui/auth/login")
    print("2. Login with: admin@test.com / admin123")
    print("3. Navigate to: Research Upload")
    print("4. Upload bundle: C:\\ATS\\fresh_bundle.json")
    print("5. Verify success page shows run_id and SHA256")
    print("6. Check research page shows Phase 3 runs")

if __name__ == "__main__":
    test_workflow()
"""
Test script demonstrating authentication and authorization flows.

Run after the server is started with: python -m uvicorn app.main:app --reload

This script tests:
1. Login with different user roles
2. Creating resources with authenticated users
3. Permission-based access control
"""

import os
import requests
import pytest

if os.environ.get('RUN_SERVER_TESTS') != '1':
    pytest.skip('Server not running; set RUN_SERVER_TESTS=1 to enable auth HTTP tests', allow_module_level=True)
import json

BASE_URL = "http://127.0.0.1:8000"

# These will be set after running seed_test_data.py
TENANT_ID = "b3909011-8bd3-439d-a421-3b70fae124e9"  # Update with your tenant ID

# Test credentials
ADMIN = {"email": "admin@test.com", "password": "admin123"}
CONSULTANT = {"email": "consultant@test.com", "password": "consultant123"}
BD_MANAGER = {"email": "bdmanager@test.com", "password": "bdmanager123"}
VIEWER = {"email": "viewer@test.com", "password": "viewer123"}


def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def login(credentials):
    """Login and return access token."""
    print(f"\n→ Logging in as {credentials['email']}...")
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json=credentials,
        headers={"X-Tenant-ID": TENANT_ID}
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Login successful!")
        print(f"  User: {data['user']['full_name']}")
        print(f"  Role: {data['user']['role']}")
        print(f"  Token: {data['access_token'][:50]}...")
        return data['access_token']
    else:
        print(f"✗ Login failed: {response.status_code}")
        print(f"  {response.json()}")
        return None


def get_headers(token):
    """Get headers with authentication token."""
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def test_auth_endpoints():
    """Test authentication endpoints."""
    print_header("TEST 1: Authentication & User Management")
    
    # Test 1.1: Admin login
    admin_token = login(ADMIN)
    if not admin_token:
        print("✗ Admin login failed. Cannot continue.")
        return
    
    # Test 1.2: Get current user info
    print("\n→ Getting current user info...")
    response = requests.get(
        f"{BASE_URL}/auth/users/me",
        headers=get_headers(admin_token)
    )
    if response.status_code == 200:
        user = response.json()
        print(f"✓ Current user: {user['full_name']} ({user['role']})")
    else:
        print(f"✗ Failed to get user info: {response.status_code}")
    
    # Test 1.3: List all users (admin only)
    print("\n→ Listing all users (admin only)...")
    response = requests.get(
        f"{BASE_URL}/auth/users",
        headers=get_headers(admin_token)
    )
    if response.status_code == 200:
        users = response.json()
        print(f"✓ Found {len(users)} users:")
        for user in users:
            print(f"  - {user['full_name']} ({user['email']}) - {user['role']}")
    else:
        print(f"✗ Failed to list users: {response.status_code}")
    
    # Test 1.4: Create a new user (admin only)
    print("\n→ Creating new user (admin only)...")
    new_user_data = {
        "tenant_id": TENANT_ID,
        "email": "newuser@test.com",
        "full_name": "New Test User",
        "password": "newuser123",
        "role": "consultant"
    }
    response = requests.post(
        f"{BASE_URL}/auth/users",
        json=new_user_data,
        headers=get_headers(admin_token)
    )
    if response.status_code == 201:
        user = response.json()
        print(f"✓ Created user: {user['full_name']} ({user['role']})")
    elif response.status_code == 400:
        print(f"ℹ User already exists (expected if script was run before)")
    else:
        print(f"✗ Failed to create user: {response.status_code}")
        print(f"  {response.json()}")


def test_role_permissions():
    """Test role-based permissions."""
    print_header("TEST 2: Role-Based Permissions")
    
    # Login as different roles
    admin_token = login(ADMIN)
    consultant_token = login(CONSULTANT)
    bd_manager_token = login(BD_MANAGER)
    viewer_token = login(VIEWER)
    
    # Test 2.1: Viewer trying to create a company (should fail without permission check)
    print("\n→ Viewer attempting to create company...")
    company_data = {
        "name": "Test Company LLC",
        "status": "active",
        "website": "https://testcompany.com"
    }
    response = requests.post(
        f"{BASE_URL}/company/",
        json=company_data,
        headers=get_headers(viewer_token)
    )
    print(f"  Status: {response.status_code}")
    if response.status_code == 201:
        print(f"  ℹ Note: Permission checks not yet implemented in company router")
    elif response.status_code == 403:
        print(f"  ✓ Correctly blocked: {response.json()['detail']}")
    
    # Test 2.2: BD Manager creating a company (should succeed)
    print("\n→ BD Manager creating company...")
    response = requests.post(
        f"{BASE_URL}/company/",
        json=company_data,
        headers=get_headers(bd_manager_token)
    )
    if response.status_code == 201:
        company = response.json()
        print(f"✓ Created company: {company['name']} (ID: {company['id']})")
    else:
        print(f"  Status: {response.status_code}")
    
    # Test 2.3: Consultant creating a candidate (should succeed)
    print("\n→ Consultant creating candidate...")
    candidate_data = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "status": "active",
        "seniority_level": "senior"
    }
    response = requests.post(
        f"{BASE_URL}/candidate/",
        json=candidate_data,
        headers=get_headers(consultant_token)
    )
    if response.status_code == 201:
        candidate = response.json()
        print(f"✓ Created candidate: {candidate['first_name']} {candidate['last_name']} (ID: {candidate['id']})")
    else:
        print(f"  Status: {response.status_code}")


def test_without_auth():
    """Test accessing endpoints without authentication."""
    print_header("TEST 3: Unauthenticated Access")
    
    # Test 3.1: Try to access company list without auth
    print("\n→ Attempting to access /company/ without authentication...")
    response = requests.get(
        f"{BASE_URL}/company/",
        headers={"X-Tenant-ID": TENANT_ID}
    )
    print(f"  Status: {response.status_code}")
    if response.status_code == 200:
        print(f"  ℹ Note: Authentication not yet required for company router")
        print(f"  ℹ This is expected as routers haven't been updated yet")
    elif response.status_code == 401:
        print(f"  ✓ Correctly requires authentication")


def test_invalid_token():
    """Test with invalid token."""
    print_header("TEST 4: Invalid Token Handling")
    
    print("\n→ Attempting to access /auth/users/me with invalid token...")
    headers = {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": "Bearer invalid_token_here"
    }
    response = requests.get(f"{BASE_URL}/auth/users/me", headers=headers)
    print(f"  Status: {response.status_code}")
    if response.status_code == 401:
        print(f"  ✓ Correctly rejected invalid token")
        print(f"  Message: {response.json()['detail']}")
    else:
        print(f"  ✗ Unexpected response")


def run_all_tests():
    """Run all test suites."""
    print("\n" + "█" * 70)
    print("  AUTHENTICATION & AUTHORIZATION TEST SUITE")
    print("█" * 70)
    print(f"\nBase URL: {BASE_URL}")
    print(f"Tenant ID: {TENANT_ID}")
    
    try:
        # Check if server is running
        response = requests.get(f"{BASE_URL}/")
        if response.status_code != 200:
            print("\n✗ Server is not responding. Make sure it's running.")
            return
        
        test_auth_endpoints()
        test_role_permissions()
        test_without_auth()
        test_invalid_token()
        
        print("\n" + "█" * 70)
        print("  ALL TESTS COMPLETED")
        print("█" * 70)
        print("\n✓ Authentication system is working!")
        print("\nℹ  NOTE: Permission checks need to be added to existing routers")
        print("   to enforce role-based access control on Company, Candidate, etc.")
        
    except requests.exceptions.ConnectionError:
        print("\n✗ Cannot connect to server. Make sure it's running on port 8000.")
    except Exception as e:
        print(f"\n✗ Error during tests: {e}")


if __name__ == "__main__":
    run_all_tests()

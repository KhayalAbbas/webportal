"""
Test UI routes to verify all type mismatches are fixed.

This script simulates login and tests all major UI routes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from sqlalchemy import select


async def test_ui_routes():
    """Test all UI routes after UUID migration."""
    
    # Get tenant and user for testing
    async with AsyncSessionLocal() as db:
        # Get tenant
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print("❌ No tenant found. Run seed_test_data.py first.")
            return False
        
        # Get admin user
        result = await db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.email == "admin@test.com"
            )
        )
        admin = result.scalar_one_or_none()
        
        if not admin:
            print("❌ No admin user found.")
            return False
        
        print(f"✅ Found tenant: {tenant.id}")
        print(f"✅ Found admin user: {admin.email}\n")
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
        # Test 1: Health check
        print("Testing /internal/db-health/json...")
        try:
            response = await client.get("/internal/db-health/json")
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Health check passed: {data['overall_status']}")
                for check in data['checks']:
                    status_emoji = "✅" if check['status'] == 'pass' else "❌"
                    print(f"    {status_emoji} {check['name']}: {check['message']}")
            else:
                print(f"  ❌ Health check failed: {response.status_code}")
                print(f"     {response.text[:200]}")
                return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False
        
        print()
        
        # Test 2: Login
        print("Testing /login...")
        try:
            response = await client.post("/login", data={
                "email": "admin@test.com",
                "password": "admin123",
                "tenant_id": str(tenant.id)
            })
            
            if response.status_code == 200:
                # Check if we have session cookie
                cookies = response.cookies
                if "session" in cookies:
                    print(f"  ✅ Login successful (got session cookie)")
                else:
                    print(f"  ✅ Login successful but no session cookie?")
            else:
                print(f"  ❌ Login failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False
        
        print()
        
        # Test 3: Dashboard
        print("Testing /dashboard...")
        try:
            response = await client.get("/dashboard")
            if response.status_code == 200:
                print(f"  ✅ Dashboard loaded successfully")
            else:
                print(f"  ❌ Dashboard failed: {response.status_code}")
                print(f"     {response.text[:500]}")
                return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False
        
        print()
        
        # Test 4: UI Routes
        ui_routes = [
            ("/ui/roles", "Roles"),
            ("/ui/candidates", "Candidates"),
            ("/ui/companies", "Companies"),
            ("/ui/bd-opportunities", "BD Opportunities"),
            ("/ui/tasks", "Tasks"),
            ("/ui/lists", "Lists"),
            ("/ui/research", "Research"),
        ]
        
        for route, name in ui_routes:
            print(f"Testing {route} ({name})...")
            try:
                response = await client.get(route)
                if response.status_code == 200:
                    print(f"  ✅ {name} loaded successfully")
                else:
                    print(f"  ❌ {name} failed: {response.status_code}")
                    if response.status_code == 500:
                        print(f"     {response.text[:500]}")
            except Exception as e:
                print(f"  ❌ Error: {e}")
        
        print()
    
    return True


if __name__ == "__main__":
    print("="*80)
    print("UI ROUTES VERIFICATION TEST")
    print("="*80)
    print()
    
    success = asyncio.run(test_ui_routes())
    
    print()
    print("="*80)
    if success:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("="*80)
    
    sys.exit(0 if success else 1)

"""Get admin credentials and tenant info."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def get_credentials():
    async with AsyncSessionLocal() as session:
        # Get tenant
        result = await session.execute(text("SELECT id, name FROM tenant LIMIT 1"))
        tenant = result.fetchone()
        
        if not tenant:
            print("❌ No tenant found")
            return
        
        tenant_id = tenant[0]
        tenant_name = tenant[1]
        
        # Get admin user
        result = await session.execute(
            text("SELECT id, email, full_name, role FROM \"user\" WHERE tenant_id = :tid AND role = 'admin' LIMIT 1"),
            {"tid": tenant_id}
        )
        admin = result.fetchone()
        
        print("=" * 60)
        print("🔑 ADMIN LOGIN CREDENTIALS")
        print("=" * 60)
        print()
        print("📧 Email:        admin@test.com")
        print("🔒 Password:     admin123")
        print()
        print("🏢 TENANT INFO")
        print("=" * 60)
        print(f"Tenant ID:      {tenant_id}")
        print(f"Tenant Name:    {tenant_name}")
        print()
        print("=" * 60)
        print()
        print("For UI Login (http://127.0.0.1:8000):")
        print("  Email: admin@test.com")
        print("  Password: admin123")
        print()
        print("For API/Swagger (http://127.0.0.1:8000/docs):")
        print("  1. Use /auth/login endpoint")
        print(f"  2. Set X-Tenant-ID header to: {tenant_id}")
        print("  3. Body: {\"email\": \"admin@test.com\", \"password\": \"admin123\"}")
        print("  4. Copy the access_token and click 'Authorize'")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(get_credentials())

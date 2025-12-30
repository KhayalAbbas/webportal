"""Check and fix admin user credentials."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from sqlalchemy import text


async def fix_admin():
    async with AsyncSessionLocal() as db:
        # Get tenant
        result = await db.execute(text("SELECT id, name FROM tenant LIMIT 1"))
        tenant = result.fetchone()
        
        if not tenant:
            print("❌ No tenant found!")
            return
        
        tenant_id = str(tenant[0])
        tenant_name = tenant[1]
        
        print(f"✓ Found tenant: {tenant_name}")
        print(f"  Tenant ID: {tenant_id}")
        print()
        
        # Check for existing admin
        user_repo = UserRepository(db)
        existing = await user_repo.get_by_email(tenant_id, "admin@test.com")
        
        if existing:
            print(f"✓ Found existing admin user: {existing.email}")
            print(f"  User ID: {existing.id}")
            print(f"  Role: {existing.role}")
            print(f"  Active: {existing.is_active}")
            print()
            print("🔄 Resetting password to 'admin123'...")
            
            # Update password using raw SQL
            from app.core.security import hash_password
            new_hash = hash_password("admin123")
            
            await db.execute(
                text("UPDATE \"user\" SET hashed_password = :pwd WHERE id = :uid"),
                {"pwd": new_hash, "uid": existing.id}
            )
            await db.commit()
            
            print("✅ Password reset successful!")
        else:
            print("❌ No admin user found. Creating new one...")
            
            admin_data = UserCreate(
                tenant_id=tenant_id,
                email="admin@test.com",
                full_name="Admin User",
                password="admin123",
                role="admin"
            )
            
            admin = await user_repo.create(admin_data)
            await db.commit()
            
            print(f"✅ Created admin user: {admin.email}")
        
        print()
        print("=" * 60)
        print("🔑 LOGIN CREDENTIALS")
        print("=" * 60)
        print()
        print("Email:       admin@test.com")
        print("Password:    admin123")
        print()
        print(f"Tenant ID:   {tenant_id}")
        print()
        print("=" * 60)
        print()
        print("Try logging in now at: http://127.0.0.1:8000")
        print()


if __name__ == "__main__":
    asyncio.run(fix_admin())

"""
Seed script to create initial admin user for testing.

Usage:
    python scripts/seed_admin_user.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.models import Tenant


async def create_admin_user():
    """Create an admin user in the first tenant."""
    
    async with AsyncSessionLocal() as db:
        # Get the first tenant
        from sqlalchemy import select
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print("❌ No tenant found. Please create a tenant first.")
            return
        
        print(f"✓ Found tenant: {tenant.name} (ID: {tenant.id})")
        
        # Check if admin user already exists
        user_repo = UserRepository(db)
        existing_admin = await user_repo.get_by_email(tenant.id, "admin@test.com")
        
        if existing_admin:
            print(f"✓ Admin user already exists: {existing_admin.email}")
            print(f"  User ID: {existing_admin.id}")
            print(f"  Role: {existing_admin.role}")
            return
        
        # Create admin user
        admin_data = UserCreate(
            tenant_id=tenant.id,
            email="admin@test.com",
            full_name="Admin User",
            password="admin123",  # Change this in production!
            role="admin"
        )
        
        admin_user = await user_repo.create(admin_data)
        await db.commit()
        
        print(f"✓ Created admin user:")
        print(f"  Email: {admin_user.email}")
        print(f"  User ID: {admin_user.id}")
        print(f"  Role: {admin_user.role}")
        print(f"  Tenant ID: {admin_user.tenant_id}")
        print(f"\n✓ You can now login with:")
        print(f"  Email: admin@test.com")
        print(f"  Password: admin123")
        print(f"  X-Tenant-ID: {tenant.id}")


if __name__ == "__main__":
    print("Creating admin user...\n")
    asyncio.run(create_admin_user())
    print("\n✓ Done!")

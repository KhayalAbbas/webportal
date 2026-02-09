"""
Seed script to create initial test tenant and admin user.

Usage:
    python scripts/seed_test_data.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from sqlalchemy import select


async def seed_test_data():
    """Create test tenant and admin user."""
    
    async with AsyncSessionLocal() as db:
        # Check if tenant exists
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            # Create tenant
            tenant = Tenant(
                name="Test Company",
                status="active"
            )
            db.add(tenant)
            await db.flush()
            await db.refresh(tenant)
            print(f"[OK] Created tenant: {tenant.name} (ID: {tenant.id})")
        else:
            print(f"[OK] Found existing tenant: {tenant.name} (ID: {tenant.id})")
        
        # Check if admin user exists
        user_repo = UserRepository(db)
        admin = await user_repo.get_by_email(tenant.id, "admin@test.com")
        
        if not admin:
            # Create admin user
            admin_data = UserCreate(
                tenant_id=tenant.id,
                email="admin@test.com",
                full_name="Admin User",
                password="admin123",
                role="admin"
            )
            admin = await user_repo.create(admin_data)
            print(f"[OK] Created admin user: {admin.email}")
        else:
            print(f"[OK] Found existing admin: {admin.email}")
        
        # Create additional test users
        test_users = [
            {
                "email": "consultant@test.com",
                "full_name": "Jane Consultant",
                "password": "consultant123",
                "role": "consultant"
            },
            {
                "email": "bdmanager@test.com",
                "full_name": "Bob BD Manager",
                "password": "bdmanager123",
                "role": "bd_manager"
            },
            {
                "email": "viewer@test.com",
                "full_name": "Alice Viewer",
                "password": "viewer123",
                "role": "viewer"
            }
        ]
        
        for user_data in test_users:
            existing = await user_repo.get_by_email(tenant.id, user_data["email"])
            if not existing:
                user = await user_repo.create(UserCreate(
                    tenant_id=tenant.id,
                    **user_data
                ))
                print(f"[OK] Created {user.role} user: {user.email}")
            else:
                print(f"[OK] Found existing {existing.role} user: {existing.email}")
        
        await db.commit()
        
        print(f"\n" + "="*60)
        print("TEST CREDENTIALS")
        print("="*60)
        print(f"\nX-Tenant-ID: {tenant.id}")
        print("\nUsers:")
        print("  Admin:        admin@test.com / admin123")
        print("  Consultant:   consultant@test.com / consultant123")
        print("  BD Manager:   bdmanager@test.com / bdmanager123")
        print("  Viewer:       viewer@test.com / viewer123")
        print("\n" + "="*60)


if __name__ == "__main__":
    print("Seeding test data...\n")
    asyncio.run(seed_test_data())
    print("\n[OK] Done!")

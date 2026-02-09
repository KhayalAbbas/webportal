"""Check and fix admin user credentials."""
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from sqlalchemy import text


async def fix_admin():
    async with AsyncSessionLocal() as db:
        # Get tenant
        result = await db.execute(text("SELECT id, name FROM tenant ORDER BY created_at ASC LIMIT 1"))
        tenant = result.fetchone()

        if not tenant:
            print("[X] No tenant found!")
            return

        tenant_id = tenant[0]  # UUID
        tenant_id_str = str(tenant_id)
        tenant_name = tenant[1]

        print(f"[OK] Found tenant: {tenant_name}")
        print(f"  Tenant ID: {tenant_id_str}")
        print()

        # Check for existing admin (get_by_email expects UUID)
        user_repo = UserRepository(db)
        existing = await user_repo.get_by_email(UUID(str(tenant_id)), "admin@test.com")
        
        if existing:
            print(f"[OK] Found existing admin user: {existing.email}")
            print(f"  User ID: {existing.id}")
            print(f"  Role: {existing.role}")
            print(f"  Active: {existing.is_active}")
            print()
            print("Resetting password to 'admin123'...")

            from app.core.security import hash_password
            new_hash = hash_password("admin123")

            await db.execute(
                text("UPDATE \"user\" SET hashed_password = :pwd WHERE id = :uid"),
                {"pwd": new_hash, "uid": existing.id}
            )
            await db.commit()

            print("[OK] Password reset successful!")
        else:
            print("[X] No admin user found. Creating new one...")

            admin_data = UserCreate(
                tenant_id=tenant_id,
                email="admin@test.com",
                full_name="Admin User",
                password="admin123",
                role="admin"
            )

            admin = await user_repo.create(admin_data)
            await db.commit()

            print(f"[OK] Created admin user: {admin.email}")

        print()
        print("=" * 60)
        print("LOGIN CREDENTIALS")
        print("=" * 60)
        print()
        print("Email:       admin@test.com")
        print("Password:    admin123")
        print()
        print(f"Tenant ID:   {tenant_id_str}")
        print()
        print("=" * 60)
        print()
        print("Try logging in at: http://127.0.0.1:8001/login")
        print()


if __name__ == "__main__":
    asyncio.run(fix_admin())

"""
Pytest configuration and shared fixtures.
"""

import os
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
import pytest


# Test credentials - these match the seeded data
TEST_ADMIN_EMAIL = "admin@test.com"
TEST_ADMIN_PASSWORD = "admin123"


async def get_test_tenant_id():
    """Get the first tenant ID from the database."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise RuntimeError(
                "No tenant found in database. "
                "Please run: python scripts/seed_test_data.py"
            )
        return str(tenant.id)


def get_tenant_id_sync():
    """Synchronous wrapper for getting tenant ID."""
    return asyncio.run(get_test_tenant_id())


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast tests, no external deps")
    config.addinivalue_line("markers", "db: requires database")
    config.addinivalue_line("markers", "server: requires running HTTP server")


def pytest_collection_modifyitems(config, items):
    run_db = os.environ.get("RUN_DB_TESTS") == "1"
    run_server = os.environ.get("RUN_SERVER_TESTS") == "1"

    skip_db = pytest.mark.skip(reason="db tests skipped by default; set RUN_DB_TESTS=1 to enable")
    skip_server = pytest.mark.skip(reason="server tests skipped by default; set RUN_SERVER_TESTS=1 to enable")

    for item in items:
        if "db" in item.keywords and not run_db:
            item.add_marker(skip_db)
        if "server" in item.keywords and not run_server:
            item.add_marker(skip_server)

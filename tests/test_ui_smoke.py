"""
Smoke tests for UI routes.

These tests verify that all main UI routes return 200 OK
for an authenticated admin user, catching 500 errors before
team testing begins.
"""

import os
import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.main import app
from app.db.session import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.role import Role
from app.models.company import Company
from app.models.bd_opportunity import BDOpportunity
from app.models.list import List
from tests.conftest import (
    TEST_ADMIN_EMAIL,
    TEST_ADMIN_PASSWORD,
    get_tenant_id_sync,
)

if os.environ.get('RUN_SERVER_TESTS') != '1':
    pytest.skip('Server/UI tests disabled; set RUN_SERVER_TESTS=1 to enable UI smoke tests', allow_module_level=True)


def get_logged_in_client():
    """
    Create a TestClient and log in with seeded admin credentials.
    Returns the client with session cookies preserved.
    """
    client = TestClient(app)
    tenant_id = get_tenant_id_sync()
    
    # POST to login endpoint
    response = client.post(
        "/login",
        data={
            "email": TEST_ADMIN_EMAIL,
            "password": TEST_ADMIN_PASSWORD,
            "tenant_id": tenant_id,
        },
        follow_redirects=False,
    )
    
    # Should redirect on successful login
    assert response.status_code in [303, 302, 307], (
        f"Login failed. Status: {response.status_code}, "
        f"Response: {response.text[:200]}"
    )
    
    # Follow the redirect to dashboard
    response = client.get("/dashboard")
    assert response.status_code == 200, (
        f"Dashboard failed after login. Status: {response.status_code}, "
        f"Response: {response.text[:200]}"
    )
    
    return client


async def get_first_entity_id(model_class, tenant_id):
    """Helper to get the first entity ID of a given type for the tenant."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(model_class.id)
            .where(model_class.tenant_id == tenant_id)
            .limit(1)
        )
        entity = result.scalar_one_or_none()
        return str(entity) if entity else None


def test_dashboard_loads_ok():
    """Test that dashboard loads without errors."""
    client = get_logged_in_client()
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_candidates_routes_ok():
    """Test candidates list and detail views."""
    client = get_logged_in_client()
    tenant_id = get_tenant_id_sync()
    
    # Test list view
    response = client.get("/ui/candidates")
    assert response.status_code == 200
    
    # Test detail view if any candidate exists
    candidate_id = asyncio.run(get_first_entity_id(Candidate, tenant_id))
    if candidate_id:
        response = client.get(f"/ui/candidates/{candidate_id}")
        assert response.status_code == 200


def test_roles_routes_ok():
    """Test roles list and detail views."""
    client = get_logged_in_client()
    tenant_id = get_tenant_id_sync()
    
    # Test list view
    response = client.get("/ui/roles")
    assert response.status_code == 200
    
    # Test detail view if any role exists
    role_id = asyncio.run(get_first_entity_id(Role, tenant_id))
    if role_id:
        response = client.get(f"/ui/roles/{role_id}")
        assert response.status_code == 200


def test_companies_routes_ok():
    """Test companies list and detail views."""
    client = get_logged_in_client()
    tenant_id = get_tenant_id_sync()
    
    # Test list view
    response = client.get("/ui/companies")
    assert response.status_code == 200
    
    # Test detail view if any company exists
    company_id = asyncio.run(get_first_entity_id(Company, tenant_id))
    if company_id:
        response = client.get(f"/ui/companies/{company_id}")
        assert response.status_code == 200


def test_bd_opportunities_routes_ok():
    """Test BD opportunities list and detail views."""
    client = get_logged_in_client()
    tenant_id = get_tenant_id_sync()
    
    # Test list view
    response = client.get("/ui/bd-opportunities")
    assert response.status_code == 200
    
    # Test detail view if any BD opportunity exists
    bd_opp_id = asyncio.run(get_first_entity_id(BDOpportunity, tenant_id))
    if bd_opp_id:
        response = client.get(f"/ui/bd-opportunities/{bd_opp_id}")
        assert response.status_code == 200


def test_tasks_route_ok():
    """Test tasks list view."""
    client = get_logged_in_client()
    
    response = client.get("/ui/tasks")
    assert response.status_code == 200


def test_lists_routes_ok():
    """Test lists list and detail views."""
    client = get_logged_in_client()
    tenant_id = get_tenant_id_sync()
    
    # Test list view
    response = client.get("/ui/lists")
    assert response.status_code == 200
    
    # Test detail view if any list exists
    list_id = asyncio.run(get_first_entity_id(List, tenant_id))
    if list_id:
        response = client.get(f"/ui/lists/{list_id}")
        assert response.status_code == 200


def test_research_route_ok():
    """Test research overview page."""
    client = get_logged_in_client()
    
    response = client.get("/ui/research")
    assert response.status_code == 200

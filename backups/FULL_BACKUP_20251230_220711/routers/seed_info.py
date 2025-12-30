"""
Internal admin-only endpoint to display seed user information.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.permissions import Roles, raise_if_not_roles
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.models.tenant import Tenant
from app.models.user import User


router = APIRouter()


@router.get("/internal/seed-info", response_class=HTMLResponse)
async def seed_info(
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    session: AsyncSession = Depends(get_db),
):
    """
    Display seed data information (admin only).
    
    Shows tenant IDs and test user credentials (except passwords).
    """
    # Permission check: admin only
    raise_if_not_roles(
        current_user.role,
        [Roles.ADMIN],
        "view seed information"
    )
    
    # Get all tenants
    tenants_query = select(Tenant).order_by(Tenant.created_at)
    tenants_result = await session.execute(tenants_query)
    tenants = tenants_result.scalars().all()
    
    # Get all users
    users_query = select(User).order_by(User.tenant_id, User.role, User.email)
    users_result = await session.execute(users_query)
    users = users_result.scalars().all()
    
    # Group users by tenant
    users_by_tenant = {}
    for user in users:
        if user.tenant_id not in users_by_tenant:
            users_by_tenant[user.tenant_id] = []
        users_by_tenant[user.tenant_id].append(user)
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Seed Data Information</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                padding: 40px;
                background: #f5f5f5;
                font-size: 14px;
            }
            .container {
                max-width: 900px;
                margin: 0 auto;
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #2c3e50;
                margin-bottom: 10px;
            }
            .subtitle {
                color: #7f8c8d;
                margin-bottom: 30px;
            }
            .tenant-section {
                margin-bottom: 40px;
                border: 1px solid #e0e0e0;
                padding: 20px;
                border-radius: 4px;
            }
            .tenant-header {
                color: #2c3e50;
                margin-bottom: 15px;
                font-size: 16px;
                font-weight: 600;
            }
            .tenant-id {
                font-family: 'Courier New', monospace;
                background: #ecf0f1;
                padding: 8px 12px;
                border-radius: 3px;
                font-size: 13px;
                margin-bottom: 15px;
                display: inline-block;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }
            th {
                background: #34495e;
                color: white;
                padding: 10px;
                text-align: left;
                font-weight: 600;
                font-size: 13px;
            }
            td {
                padding: 10px;
                border-bottom: 1px solid #e0e0e0;
            }
            tr:hover {
                background: #f8f9fa;
            }
            .role-badge {
                display: inline-block;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
            }
            .role-admin {
                background: #e74c3c;
                color: white;
            }
            .role-consultant {
                background: #3498db;
                color: white;
            }
            .role-bd_manager {
                background: #9b59b6;
                color: white;
            }
            .role-viewer {
                background: #95a5a6;
                color: white;
            }
            .note {
                background: #fff3cd;
                border: 1px solid #ffc107;
                padding: 15px;
                border-radius: 4px;
                margin-top: 30px;
                font-size: 13px;
            }
            .note strong {
                color: #856404;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Seed Data Information</h1>
            <p class="subtitle">Tenant and user credentials for testing</p>
    """
    
    for tenant in tenants:
        tenant_users = users_by_tenant.get(tenant.id, [])
        
        html += f"""
            <div class="tenant-section">
                <div class="tenant-header">{tenant.name}</div>
                <div class="tenant-id">Tenant ID: {tenant.id}</div>
                
                <table>
                    <thead>
                        <tr>
                            <th>Email</th>
                            <th>Full Name</th>
                            <th>Role</th>
                            <th>Default Password</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        # Default passwords for known test users
        default_passwords = {
            "admin@test.com": "admin123",
            "consultant@test.com": "consultant123",
            "bdmanager@test.com": "bdmanager123",
            "viewer@test.com": "viewer123",
        }
        
        for user in tenant_users:
            role_class = f"role-{user.role}"
            password = default_passwords.get(user.email, "N/A")
            
            html += f"""
                        <tr>
                            <td>{user.email}</td>
                            <td>{user.full_name}</td>
                            <td><span class="role-badge {role_class}">{user.role}</span></td>
                            <td><code>{password}</code></td>
                        </tr>
            """
        
        html += """
                    </tbody>
                </table>
            </div>
        """
    
    html += """
            <div class="note">
                <strong>Note:</strong> This page is only accessible to admin users.
                Default passwords are shown for test/seed users only. 
                Production passwords are not displayed.
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

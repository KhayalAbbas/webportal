# Authentication System - Quick Start Guide

## Overview

Your ATS backend now has a complete JWT-based authentication system with role-based permissions.

## Test Credentials

After running `python scripts/seed_test_data.py`, you'll have these users:

**Tenant ID:** `b3909011-8bd3-439d-a421-3b70fae124e9` (update with yours)

**Users:**
- Admin: `admin@test.com` / `admin123`
- Consultant: `consultant@test.com` / `consultant123`
- BD Manager: `bdmanager@test.com` / `bdmanager123`
- Viewer: `viewer@test.com` / `viewer123`

## Roles & Permissions

| Role | Permissions |
|------|-------------|
| `admin` | Full access, can manage users |
| `consultant` | Manage candidates, roles, assignments, tasks |
| `bd_manager` | Manage companies, contacts, BD opportunities, tasks |
| `viewer` | Read-only access |

## API Usage Examples

### 1. Login

**Request:**
```bash
curl -X POST "http://127.0.0.1:8000/auth/login" \
  -H "X-Tenant-ID: b3909011-8bd3-439d-a421-3b70fae124e9" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@test.com",
    "password": "admin123"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "8f4941c8-efd8-48ee-9781-02a1be4a1479",
    "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
    "email": "admin@test.com",
    "full_name": "Admin User",
    "role": "admin",
    "is_active": true,
    "created_at": "2024-12-09T20:23:53.397391+00:00",
    "updated_at": "2024-12-09T20:23:53.397391+00:00"
  }
}
```

### 2. Get Current User Info

**Request:**
```bash
curl -X GET "http://127.0.0.1:8000/auth/users/me" \
  -H "X-Tenant-ID: b3909011-8bd3-439d-a421-3b70fae124e9" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### 3. List All Users (Admin Only)

**Request:**
```bash
curl -X GET "http://127.0.0.1:8000/auth/users" \
  -H "X-Tenant-ID: b3909011-8bd3-439d-a421-3b70fae124e9" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### 4. Create New User (Admin Only)

**Request:**
```bash
curl -X POST "http://127.0.0.1:8000/auth/users" \
  -H "X-Tenant-ID: b3909011-8bd3-439d-a421-3b70fae124e9" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
    "email": "newuser@test.com",
    "full_name": "New User",
    "password": "newpass123",
    "role": "consultant"
  }'
```

### 5. Create Company (Authenticated)

**Request:**
```bash
curl -X POST "http://127.0.0.1:8000/company/" \
  -H "X-Tenant-ID: b3909011-8bd3-439d-a421-3b70fae124e9" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corporation",
    "status": "active",
    "website": "https://acme.com"
  }'
```

## PowerShell Examples

### Login
```powershell
$tenantId = "b3909011-8bd3-439d-a421-3b70fae124e9"
$loginBody = @{
    email = "admin@test.com"
    password = "admin123"
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/auth/login" `
    -Method POST `
    -Headers @{"X-Tenant-ID"=$tenantId; "Content-Type"="application/json"} `
    -Body $loginBody

$token = $response.access_token
Write-Host "Logged in as: $($response.user.full_name)"
Write-Host "Token: $token"
```

### Get Current User
```powershell
$headers = @{
    "X-Tenant-ID" = $tenantId
    "Authorization" = "Bearer $token"
}

$user = Invoke-RestMethod -Uri "http://127.0.0.1:8000/auth/users/me" `
    -Method GET `
    -Headers $headers

Write-Host "Current user: $($user.full_name) ($($user.role))"
```

### Create Company
```powershell
$companyBody = @{
    name = "Test Company Inc"
    status = "active"
    website = "https://testcompany.com"
} | ConvertTo-Json

$company = Invoke-RestMethod -Uri "http://127.0.0.1:8000/company/" `
    -Method POST `
    -Headers $headers `
    -Body $companyBody

Write-Host "Created company: $($company.name) (ID: $($company.id))"
```

## How It Works

### Authentication Flow

1. **Login**: User sends email + password with X-Tenant-ID header
2. **Token Generation**: Server validates credentials and returns JWT token
3. **Authenticated Requests**: Client includes token in Authorization header
4. **Token Validation**: Server validates token, loads user, checks tenant access

### Security Features

- **Password Hashing**: bcrypt with salts
- **JWT Tokens**: 24-hour expiration, contains user_id, tenant_id, email, role
- **Multi-Tenancy**: Users are scoped to tenants, email unique per tenant
- **Role-Based Access**: Permission checks based on user role
- **Inactive Users**: Can block users by setting `is_active = false`

### Token Payload Example

```json
{
  "user_id": "8f4941c8-efd8-48ee-9781-02a1be4a1479",
  "tenant_id": "b3909011-8bd3-439d-a421-3b70fae124e9",
  "email": "admin@test.com",
  "role": "admin",
  "exp": 1702246800
}
```

## Next Steps

### Required: Update Existing Routers

The authentication system is built, but existing routers (Company, Candidate, etc.) still need to be updated to require authentication:

1. **Add Authentication Dependency**:
```python
from app.core.dependencies import verify_user_tenant_access

@router.get("/")
async def list_companies(
    current_user: User = Depends(verify_user_tenant_access),  # Add this
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    # ... existing code
```

2. **Add Permission Checks** (Optional but recommended):
```python
from app.core.dependencies import require_role

@router.post("/", dependencies=[Depends(require_role("admin", "bd_manager"))])
async def create_company(...):
    # Only admins and BD managers can create companies
```

3. **Track Created By** (for audit trail):
```python
@router.post("/")
async def create_company(
    company_data: CompanyCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    # Add created_by field to track who created the record
    # (Requires schema/model updates)
```

### Optional Enhancements

- **Refresh Tokens**: Implement refresh tokens for longer sessions
- **Password Reset**: Email-based password reset flow
- **User Profile Updates**: Allow users to update their own profiles
- **Audit Logging**: Track all authentication events
- **Rate Limiting**: Prevent brute force attacks on login
- **2FA**: Two-factor authentication for enhanced security

## Testing

### Run Automated Tests

```bash
python scripts/test_authentication.py
```

### Test with FastAPI Docs

1. Start server: `python -m uvicorn app.main:app --reload`
2. Open: http://127.0.0.1:8000/docs
3. Click "Authorize" button (top right)
4. Login first via `/auth/login` to get token
5. Enter token in format: `Bearer YOUR_TOKEN_HERE`
6. Try authenticated endpoints

## Troubleshooting

### "Invalid authentication credentials"
- Token expired (24 hours)
- Token malformed or invalid
- User was deactivated
- Solution: Login again to get new token

### "User does not have access to tenant"
- X-Tenant-ID doesn't match user's tenant
- Solution: Ensure X-Tenant-ID matches user's tenant_id

### "Requires one of roles: admin, bd_manager"
- User doesn't have required role
- Solution: Login with user that has correct role, or have admin update user role

### "Email already registered in this tenant"
- Email already exists for that tenant
- Solution: Use different email or login with existing account

## Production Checklist

Before deploying to production:

- [ ] Change SECRET_KEY in `.env` (use strong random string, min 32 chars)
- [ ] Set secure password requirements (min length, complexity)
- [ ] Enable HTTPS/TLS for all API traffic
- [ ] Implement rate limiting on login endpoint
- [ ] Add refresh token mechanism
- [ ] Set up monitoring for failed login attempts
- [ ] Configure CORS properly for your frontend domain
- [ ] Review and update token expiration time
- [ ] Implement password reset flow
- [ ] Add audit logging for authentication events
- [ ] Set up alerts for suspicious activity

## Files Created

### Core Authentication
- `app/models/user.py` - User model with authentication fields
- `app/core/security.py` - Password hashing with bcrypt
- `app/core/jwt.py` - JWT token creation/validation
- `app/core/dependencies.py` - Authentication dependencies (updated)
- `app/core/config.py` - Auth settings (updated)

### Schemas & Business Logic
- `app/schemas/user.py` - User validation schemas
- `app/repositories/user_repository.py` - User database operations
- `app/services/auth_service.py` - Authentication service
- `app/routers/auth.py` - Authentication endpoints

### Database
- `alembic/versions/003_add_user_auth.py` - User table migration

### Scripts
- `scripts/seed_test_data.py` - Seed test tenant and users
- `scripts/test_authentication.py` - Automated test suite

## API Documentation

Full API documentation available at:
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

# Authentication Quick Reference

## 🚀 Quick Start

### 1. Setup Database
```bash
# Apply migration
alembic upgrade head
```

### 2. Seed Test Data
```bash
python scripts/seed_test_data.py
```

### 3. Start Server
```bash
python -m uvicorn app.main:app --reload
```

### 4. Test Login
```bash
# PowerShell
$body = @{email="admin@test.com"; password="admin123"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/auth/login" `
  -Method POST `
  -Headers @{"X-Tenant-ID"="YOUR_TENANT_ID"; "Content-Type"="application/json"} `
  -Body $body
```

## 📋 Test Credentials

**Tenant ID:** Run `python scripts/seed_test_data.py` to see yours

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@test.com | admin123 |
| Consultant | consultant@test.com | consultant123 |
| BD Manager | bdmanager@test.com | bdmanager123 |
| Viewer | viewer@test.com | viewer123 |

## 🔑 Using Authentication

### In PowerShell
```powershell
# 1. Login
$login = Invoke-RestMethod -Uri "http://127.0.0.1:8000/auth/login" `
  -Method POST `
  -Headers @{"X-Tenant-ID"="YOUR_TENANT_ID"; "Content-Type"="application/json"} `
  -Body (@{email="admin@test.com"; password="admin123"} | ConvertTo-Json)

$token = $login.access_token

# 2. Use token in requests
$headers = @{
  "X-Tenant-ID" = "YOUR_TENANT_ID"
  "Authorization" = "Bearer $token"
  "Content-Type" = "application/json"
}

# 3. Make authenticated request
Invoke-RestMethod -Uri "http://127.0.0.1:8000/auth/users/me" -Headers $headers
```

### In curl
```bash
# 1. Login
curl -X POST "http://127.0.0.1:8000/auth/login" \
  -H "X-Tenant-ID: YOUR_TENANT_ID" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"admin123"}'

# 2. Save token from response
TOKEN="eyJhbGciOiJIUzI1..."

# 3. Use in requests
curl "http://127.0.0.1:8000/auth/users/me" \
  -H "X-Tenant-ID: YOUR_TENANT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## 🛡️ Role Permissions

| Role | Can Do |
|------|--------|
| **admin** | Everything + manage users |
| **consultant** | Candidates, Roles, Assignments, Tasks |
| **bd_manager** | Companies, Contacts, BD Opportunities, Tasks |
| **viewer** | Read-only access to all |

## 📡 Auth Endpoints

### `POST /auth/login`
Login and get JWT token
- Headers: `X-Tenant-ID`
- Body: `{"email": "...", "password": "..."}`
- Returns: JWT token + user data

### `GET /auth/users/me`
Get current user info
- Headers: `X-Tenant-ID`, `Authorization: Bearer TOKEN`
- Returns: Current user data

### `GET /auth/users`
List all users (admin only)
- Headers: `X-Tenant-ID`, `Authorization: Bearer TOKEN`
- Query: `?skip=0&limit=50`
- Returns: Array of users

### `POST /auth/users`
Create new user (admin only)
- Headers: `X-Tenant-ID`, `Authorization: Bearer TOKEN`
- Body: User data with password
- Returns: New user data

### `PATCH /auth/users/{user_id}`
Update user (admin only)
- Headers: `X-Tenant-ID`, `Authorization: Bearer TOKEN`
- Body: Fields to update
- Returns: Updated user data

## 🔧 Adding Auth to Existing Routes

### Add Authentication Requirement
```python
from app.core.dependencies import verify_user_tenant_access
from app.models.user import User

@router.get("/")
async def list_companies(
    current_user: User = Depends(verify_user_tenant_access),  # Add this
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    # Now authenticated, current_user available
    # Existing code works unchanged
```

### Add Permission Check
```python
from app.core.dependencies import require_role

@router.post("/", dependencies=[Depends(require_role("admin", "bd_manager"))])
async def create_company(
    company_data: CompanyCreate,
    current_user: User = Depends(verify_user_tenant_access),
    db: AsyncSession = Depends(get_db),
):
    # Only admin and bd_manager can access
```

## 🐛 Common Issues

### "Invalid authentication credentials"
- Token expired (24 hours)
- Token format wrong (must be: `Bearer YOUR_TOKEN`)
- Solution: Login again

### "User does not have access to tenant"
- X-Tenant-ID doesn't match user's tenant
- Solution: Use correct tenant ID

### "Requires one of roles: ..."
- User role doesn't have permission
- Solution: Login with different role

### "Email already registered"
- Email exists in that tenant
- Solution: Use different email or login

## 📁 Key Files

| File | Purpose |
|------|---------|
| `app/models/user.py` | User database model |
| `app/routers/auth.py` | Auth endpoints |
| `app/core/dependencies.py` | Auth dependencies |
| `app/core/security.py` | Password hashing |
| `app/core/jwt.py` | JWT tokens |
| `docs/AUTHENTICATION.md` | Full documentation |

## 🎯 Next Steps

1. **Test authentication** - Verify login works
2. **Update routers** - Add auth to existing endpoints
3. **Add permissions** - Use `require_role()` for specific routes
4. **Change SECRET_KEY** - Use secure key in production

## 📚 Documentation

- Full guide: `docs/AUTHENTICATION.md`
- Implementation details: `docs/AUTH_IMPLEMENTATION_SUMMARY.md`
- API docs: http://127.0.0.1:8000/docs

## 💡 Tips

- Tokens expire in 24 hours
- Email must be unique per tenant
- Passwords are bcrypt hashed
- Inactive users cannot login
- All requests need X-Tenant-ID + Authorization headers
- Use FastAPI docs to test easily: http://127.0.0.1:8000/docs

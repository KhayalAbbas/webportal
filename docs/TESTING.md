# UI Smoke Test Suite

## Overview

Automated smoke tests to verify all main UI routes return 200 OK for authenticated users, catching 500 errors before team testing.

## Test Files

### `tests/__init__.py`
Package marker for tests directory.

### `tests/conftest.py`
Pytest configuration with shared test credentials:
- `TEST_ADMIN_EMAIL`: admin@test.com
- `TEST_ADMIN_PASSWORD`: admin123
- `get_test_tenant_id()`: Fetches the seeded tenant ID from database
- `get_tenant_id_sync()`: Synchronous wrapper for tenant ID lookup

### `tests/test_ui_smoke.py`
Main smoke test suite with the following tests:

#### Helper Functions
- **`get_logged_in_client()`**: Creates a TestClient, logs in with seeded admin credentials, and returns the authenticated client with session cookies preserved

- **`get_first_entity_id(model_class, tenant_id)`**: Async helper to fetch the first entity ID of a given type for testing detail views

#### Test Coverage

1. **`test_dashboard_loads_ok()`**
   - Tests: `GET /dashboard`
   - Verifies: Dashboard loads without errors after login

2. **`test_candidates_routes_ok()`**
   - Tests: `GET /ui/candidates` (list view)
   - If candidates exist: `GET /ui/candidates/{id}` (detail view)
   - Verifies: Candidates module is accessible and functional

3. **`test_roles_routes_ok()`**
   - Tests: `GET /ui/roles` (list view)
   - If roles exist: `GET /ui/roles/{id}` (detail view)
   - Verifies: Roles module is accessible and functional

4. **`test_companies_routes_ok()`**
   - Tests: `GET /ui/companies` (list view)
   - If companies exist: `GET /ui/companies/{id}` (detail view)
   - Verifies: Companies module is accessible and functional

5. **`test_bd_opportunities_routes_ok()`**
   - Tests: `GET /ui/bd-opportunities` (list view)
   - If BD opportunities exist: `GET /ui/bd-opportunities/{id}` (detail view)
   - Verifies: BD Opportunities module is accessible and functional

6. **`test_tasks_route_ok()`**
   - Tests: `GET /ui/tasks`
   - Verifies: Tasks module loads without errors

7. **`test_lists_routes_ok()`**
   - Tests: `GET /ui/lists` (list view)
   - If lists exist: `GET /ui/lists/{id}` (detail view)
   - Verifies: Lists module is accessible and functional

8. **`test_research_route_ok()`**
   - Tests: `GET /ui/research`
   - Verifies: Research overview page loads without errors

## Prerequisites

1. **Seeded Data Required**: Run `python scripts/seed_test_data.py` before running tests
2. **Database Running**: PostgreSQL must be running with the configured database
3. **Dependencies**: Install pytest with `pip install -r requirements.txt`

## Test Design Principles

### Deterministic
- Uses existing seeded data from development database
- No random data generation
- Predictable test outcomes

### Fast
- Mostly read operations
- Single login POST per test
- No external API calls
- No sleep/delays

### Resilient
- Tests gracefully handle empty tables
- If no entities exist, detail view tests are skipped
- Only list views are required to pass

### Non-Invasive
- No writes to database (except session creation)
- Safe to run repeatedly
- Does not modify application state

## What These Tests Catch

✓ 500 Internal Server Errors on any UI route  
✓ Missing `current_user` in template context (sidebar disappearing)  
✓ AttributeErrors from incorrect model fields  
✓ Broken async query patterns  
✓ Authentication/session issues  
✓ Template rendering errors  
✓ Route configuration problems  

## What These Tests Don't Cover

✗ API endpoints (only UI routes tested)  
✗ Permission checks (uses admin with full access)  
✗ Form submissions (only GET requests)  
✗ JavaScript functionality  
✗ Complex business logic  
✗ Edge cases and validation  

## Confirmation

When pytest runs successfully:
- **All tests pass** = All main UI routes return 200 OK for authenticated admin user
- **Tests are collected** = pytest finds and recognizes all test functions
- **No setup errors** = Database connection works, tenant exists, credentials are valid

## Running the Tests

```bash
# From project root
pytest tests/

# Verbose output
pytest tests/ -v

# Run specific test
pytest tests/test_ui_smoke.py::test_dashboard_loads_ok

# Run with output
pytest tests/ -v -s
```

## Expected Output

```
============================= test session starts ==============================
collected 8 items

tests/test_ui_smoke.py::test_dashboard_loads_ok PASSED                  [ 12%]
tests/test_ui_smoke.py::test_candidates_routes_ok PASSED                [ 25%]
tests/test_ui_smoke.py::test_roles_routes_ok PASSED                     [ 37%]
tests/test_ui_smoke.py::test_companies_routes_ok PASSED                 [ 50%]
tests/test_ui_smoke.py::test_bd_opportunities_routes_ok PASSED          [ 62%]
tests/test_ui_smoke.py::test_tasks_route_ok PASSED                      [ 75%]
tests/test_ui_smoke.py::test_lists_routes_ok PASSED                     [ 87%]
tests/test_ui_smoke.py::test_research_route_ok PASSED                   [100%]

============================== 8 passed in 2.34s ===============================
```

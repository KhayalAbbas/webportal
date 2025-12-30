# ATS Development Environment - READ FIRST

## ⚠️ CRITICAL: Python Environment

**This project has a virtual environment at `.venv\`**

### Two Ways to Run (Both Work!)

#### Option 1: Use Global Python (Currently Running)
```powershell
# Just use python directly - packages installed globally too
python -m uvicorn app.main:app --reload
pip install <package>
```

#### Option 2: Use Venv (Best Practice)
```powershell
# Activate venv first
.\.venv\Scripts\Activate.ps1

# Then run commands
python -m uvicorn app.main:app --reload
pip install <package>

# To deactivate
deactivate
```

### Quick Commands

```powershell
# Start server (using whatever Python is active)
python -m uvicorn app.main:app --reload --port 8000

# Start server (explicitly using venv)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Check which Python you're using
python -c "import sys; print(sys.executable)"
# Global: C:\Users\Iulian2\AppData\Local\Programs\Python\Python311\python.exe
# Venv:   C:\ATS\.venv\Scripts\python.exe
```

### Current Status

- ✅ Venv exists at `.venv\`
- ✅ Packages installed in BOTH global and venv
- ✅ Server works either way
- 💡 Recommendation: Use venv activation for cleaner isolation

### Database

- **PostgreSQL** running locally
- Connection string in `.env` file
- Database name: `ats_db`

### Server

- Default port: `8000`
- Access at: `http://localhost:8000`
- Admin UI: `http://localhost:8000/dashboard`

## Project Structure

```
c:\ATS\
├── venv\              # Virtual environment - DO NOT COMMIT
├── app\
│   ├── ui\           # UI routes and templates
│   ├── api\          # REST API endpoints
│   ├── models\       # SQLAlchemy models
│   ├── schemas\      # Pydantic schemas
│   └── repositories\ # Data access layer
├── docs\             # Documentation
└── scripts\          # Utility scripts
```

## Recent Fixes

- ✅ All CRUD features implemented (Candidates, Companies, Roles, Contacts, BD Opportunities, Tasks, Lists)
- ✅ Repository method signatures fixed (tenant_id as first parameter)
- ✅ Date field handling (datetime parsing)
- ✅ Permission checks corrected

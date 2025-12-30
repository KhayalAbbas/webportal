# ATS + Agentic Research Engine - Architecture Documentation

## Overview

This is the backend foundation for a SaaS Applicant Tracking System (ATS) combined with an Agentic Research Engine. The system helps executive search firms manage candidates, companies, roles, and research activities.

## Technology Stack

| Component | Technology | Why We Chose It |
|-----------|------------|-----------------|
| **Web Framework** | FastAPI | Fast, modern, automatic API docs, great for async |
| **Database** | PostgreSQL 15+ | Reliable, supports JSONB, great for complex queries |
| **ORM** | SQLAlchemy (async) | Industry standard, type-safe, works well with FastAPI |
| **DB Driver** | asyncpg | Fastest PostgreSQL driver for Python async |
| **Migrations** | Alembic | Standard tool for SQLAlchemy migrations |
| **Validation** | Pydantic | Automatic data validation and serialization |

## Project Structure

```
ATS/
├── app/                          # Main application code
│   ├── main.py                   # FastAPI app entry point
│   ├── core/
│   │   └── config.py             # Settings (DATABASE_URL, etc.)
│   ├── db/
│   │   ├── base.py               # SQLAlchemy declarative base
│   │   └── session.py            # Database connection and sessions
│   ├── models/                   # SQLAlchemy models (database tables)
│   │   ├── tenant.py
│   │   ├── company.py
│   │   ├── contact.py
│   │   ├── candidate.py
│   │   ├── role.py
│   │   ├── pipeline_stage.py
│   │   ├── activity_log.py
│   │   ├── research_event.py
│   │   ├── source_document.py
│   │   └── ai_enrichment_record.py
│   ├── schemas/                  # Pydantic schemas (API data structures)
│   │   └── (matching schemas for each model)
│   ├── routers/                  # API endpoints
│   │   └── health.py             # Health check endpoints
│   ├── services/                 # Business logic (to be implemented)
│   └── repositories/             # Database operations (to be implemented)
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration files
│   │   └── 001_initial.py        # Initial schema migration
│   └── env.py                    # Alembic configuration
├── docs/
│   └── architecture.md           # This file
├── alembic.ini                   # Alembic settings
├── requirements.txt              # Python dependencies
├── .env.example                  # Example environment variables
└── .env                          # Your local environment (create this!)
```

## Multi-Tenancy Strategy

We use a **shared database with tenant_id column** approach:

- **One database** for all customers
- Every tenant-scoped table has a `tenant_id` column
- All queries filter by `tenant_id` to keep data isolated
- Simple to manage, easy to scale

**Important:** Always filter by `tenant_id` in your queries!

## Data Model

### Entity Relationship Diagram (Simplified)

```
Tenant (global)
    |
    +-- Company (tenant-scoped)
    |       |
    |       +-- Contact (people at the company)
    |       +-- Role (job openings)
    |
    +-- Candidate (job seekers)
    |
    +-- PipelineStage (recruitment stages)
    |
    +-- ActivityLog (audit trail)
    |
    +-- ResearchEvent
    |       |
    |       +-- SourceDocument
    |
    +-- AIEnrichmentRecord
```

### Primary Key Strategy

All tables use **UUID** primary keys:
- Globally unique (no collisions across tables or databases)
- Can be generated client-side
- Better for distributed systems

### Common Fields

All tenant-scoped tables have:
- `id` (UUID) - primary key
- `tenant_id` (string) - which tenant owns this data
- `created_at` (timestamp with timezone) - when created
- `updated_at` (timestamp with timezone) - when last modified

## Database Indexes

We've added indexes for performance:

| Table | Index | Purpose |
|-------|-------|---------|
| All tables | `tenant_id` | Fast filtering by tenant |
| Contact | `(tenant_id, company_id)` | Find contacts at a company |
| Role | `(tenant_id, company_id)` | Find roles at a company |
| ActivityLog | `occurred_at` | Time-based queries |

## How to Set Up Locally

### Step 1: Install PostgreSQL

1. Download PostgreSQL from https://www.postgresql.org/download/windows/
2. During installation, note your password for the `postgres` user
3. Create a database called `ats_db`:
   - Open pgAdmin (installed with PostgreSQL)
   - Right-click "Databases" → Create → Database
   - Name it `ats_db`

### Step 2: Create Environment File

Copy `.env.example` to `.env` and update with your database credentials:

```
DATABASE_URL=postgresql+asyncpg://postgres:your_password@localhost:5432/ats_db
APP_NAME=ATS Research Engine
DEBUG=true
```

**Breaking down the DATABASE_URL:**
- `postgresql+asyncpg://` - use PostgreSQL with async driver
- `postgres` - database username
- `your_password` - your PostgreSQL password
- `localhost` - database is on your computer
- `5432` - default PostgreSQL port
- `ats_db` - database name

### Step 3: Install Python Dependencies

Open a terminal in the project folder and run:

```powershell
# Create a virtual environment (recommended)
python -m venv venv

# Activate it
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Step 4: Run Database Migrations

This creates all the database tables:

```powershell
# Make sure you're in the project root (where alembic.ini is)
alembic upgrade head
```

**What this does:**
- Reads the migration files in `alembic/versions/`
- Creates all the tables defined in the migrations
- Tracks which migrations have been applied

### Step 5: Start the Server

```powershell
uvicorn app.main:app --reload
```

**What this means:**
- `app.main:app` - look in `app/main.py` for the `app` object
- `--reload` - restart when code changes (for development)

The server will start at: **http://localhost:8000**

### Step 6: Test It!

- Open http://localhost:8000 - should see welcome message
- Open http://localhost:8000/docs - interactive API documentation
- Open http://localhost:8000/health - health check
- Open http://localhost:8000/health/db - database health check

## Common Commands

| What You Want | Command |
|---------------|---------|
| Start server | `uvicorn app.main:app --reload` |
| Run migrations | `alembic upgrade head` |
| Create new migration | `alembic revision --autogenerate -m "description"` |
| Rollback last migration | `alembic downgrade -1` |
| See migration history | `alembic history` |
| See current version | `alembic current` |

## Next Steps (Future Development)

1. **Add CRUD routers** for each entity (create, read, update, delete)
2. **Add authentication** (JWT tokens, user management)
3. **Add full-text search** on candidate CVs
4. **Implement services layer** for business logic
5. **Add research engine** integration
6. **Add AI enrichment** workflows

## Troubleshooting

### "Connection refused" error
- Make sure PostgreSQL is running
- Check your DATABASE_URL in `.env`
- Make sure the database `ats_db` exists

### "Import could not be resolved" in VS Code
- This is just the IDE - packages aren't installed yet
- Run `pip install -r requirements.txt` to fix

### Migration errors
- Make sure you're in the project root (where `alembic.ini` is)
- Check that DATABASE_URL is correct in `.env`
- Try `alembic current` to see the current state

## Questions?

The code is designed to be simple and readable. Each file has comments explaining what it does. Start with:
1. `app/main.py` - the entry point
2. `app/models/` - see how tables are defined
3. `app/schemas/` - see how API data is structured

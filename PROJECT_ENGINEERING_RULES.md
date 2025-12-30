# PROJECT ENGINEERING RULES

(Claude must review these before any coding or refactoring task)

## 1. Models and Database Migrations Must Always Match

Whenever a SQLAlchemy model is added or modified:

- Generate a new Alembic migration (`--autogenerate` if appropriate).
- Open and inspect the migration file:
  - Ensure all new fields appear in the migration.
  - Remove any accidental leftovers or wrong diff guesses.
- Ensure Postgres schema = SQLAlchemy model after running:
  ```
  alembic upgrade head
  ```

If any API/UI call produces an error like:
- "column X does not exist"
- "table Y has no column Z"

then the cause is **model–migration mismatch**, and Claude must fix that migration immediately.

## 2. Backend Must Always Be Wired Into UI

Whenever a new feature is added:

- New FastAPI router → must be imported into the main app.
- New UI route (`/ui/...`) → must correspond to a real backend endpoint and a real template/component.
- Every button in the UI → must call a real API endpoint.

## 3. User Testing Path Must Always Be Clear

Before saying "done", Claude must provide:

- A short step-by-step guide for Iulian to test the feature in the browser.
- What he should see at each step.
- No request for Postman, Swagger, or raw API usage unless explicitly asked.

## 4. Logs Must Have Zero 500 Errors After Changes

Claude must self-check:

- Start the app.
- Trigger the relevant UI page(s).
- Ensure no server-side exceptions or SQL errors appear in the logs.
- If any appear → fix before saying "ready".

## 5. Multi-Tenant Rules Must Stay Consistent

If the project uses `tenant_id`:

- New tables must include `tenant_id` unless we explicitly decide otherwise.
- Queries must filter by `tenant_id` when appropriate.

## 6. Developer-Only Helpers Must Be Clearly Marked

If dummy data generators or debugging endpoints are added:

- They must be clearly labeled in code.
- EASY to remove cleanly later.

## 7. All Diagnostics and Checks Must Be Script Files

**Never use `python -c "..."` for anything non-trivial.**

**Never write async code inside shell one-liners.**

All diagnostics, checks, or experiments must be written as:

```
scripts/<descriptive_name>.py
```

Scripts must be runnable via:

```bash
python scripts/<file>.py
```

**Rules:**
- If a check is useful more than once, it must remain in the repository.
- If you need to inspect DB schema, create scripts like:
  - `scripts/check_tables.py`
  - `scripts/check_columns.py`
  - `scripts/smoke_company_research.py`
- Do not assume Linux shell features (no `&&`, `|`, etc. in commands).
- Assume **Windows + async stack** (use `asyncio.run()`, not shell piping).

**Examples of what to avoid:**
```bash
# ❌ BAD - async code in shell one-liner
python -c "import asyncio; from app.db.session import AsyncSessionLocal; ..."

# ❌ BAD - complex logic in shell command
python -c "import sys; sys.path.insert(0, '.'); from app.models import User; print(User.__table__.columns)"
```

**Examples of what to do:**
```bash
# ✅ GOOD - dedicated script file
python scripts/check_columns.py
python scripts/smoke_company_research.py
```

---

## ❗ Claude must follow this workflow before any coding:

Before starting any coding task, Claude must:

1. Load and read `PROJECT_ENGINEERING_RULES.md`
2. Confirm understanding
3. Apply these rules during implementation
4. Validate the result against these rules before replying "done"

---

END OF FILE

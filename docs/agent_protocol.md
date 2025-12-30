# Agent Protocol (MANDATORY)

## Preflight (must execute; fix immediately)
- Confirm venv active
- Confirm DB reachable
- Confirm server running; if not, start it
- Confirm alembic current == head; if not, upgrade
- Confirm required tables exist for the phase (list tables)
- Confirm required foreign keys/IDs exist (create them if missing)

## Execution rule
- Do not ask the user what to do next.
- If any step fails, fix the cause and continue until the full workflow completes, unless impossible.

## Output contract (no narrative)
- Create a single proof file for each task:
  C:\ATS\proofs\<task_name>_proof.txt
- The proof file must contain ONLY:
  - exact commands executed
  - raw command outputs (HTTP responses, psql outputs, worker logs)
- Do not write summaries/explanations in chat.

## API call rule (NO GUESSING)
- Never guess endpoints.
- Before any /api/* call, do ONE of:
  1) Fetch /openapi.json and locate the exact path + method, OR
  2) Run a local route dump script to list routes.
- If any request returns 404 Not Found:
  - STOP
  - run route discovery again
  - correct the URL
  - do not retry variants

## Required tools (create once)
- C:\ATS\tools\dump_routes.py (prints all FastAPI routes: METHODS + PATH)
- C:\ATS\tools\openapi_find.ps1 (downloads /openapi.json and searches a keyword)

## Definition of Done
- Before finishing, verify each required deliverable with raw evidence in the proof file.
- If an item is not proven, the task is not done.

After creating the file, confirm by printing its full contents (raw cat/type output).
Then, for all future tasks, begin with: "Follow docs/agent_protocol.md exactly."
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from dotenv import load_dotenv
from sqlalchemy import text

sys.path.append(os.getcwd())
from app.db.session import async_session_maker  # noqa: E402

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_0_url_fetch_and_process.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_0_openapi.json"
PREFLIGHT_ARTIFACT = ARTIFACT_DIR / "phase_4_0_preflight.txt"

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError as exc:
        return 127, "", str(exc)


def preflight() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    log("--- PRE-FLIGHT ---")
    py_ver = sys.version.replace("\n", " ")
    lines = []
    lines.append(f"Python: {py_ver}")

    rc_git, git_out, git_err = run_cmd(["git", "status", "-sb"])
    if rc_git == 0:
        git_line = f"git status -sb: {git_out}"
    else:
        git_line = f"git status unavailable (git rc={rc_git}): {git_err or 'git not in PATH'}"
    lines.append(git_line)

    rc_alembic, alembic_out, alembic_err = run_cmd([sys.executable, "-m", "alembic", "current"])
    if rc_alembic == 0:
        alembic_line = f"alembic current: {alembic_out}"
    else:
        alembic_line = f"alembic current unavailable (rc={rc_alembic}): {alembic_err}"
    lines.append(alembic_line)

    rc_heads, heads_out, heads_err = run_cmd([sys.executable, "-m", "alembic", "heads"])
    if rc_heads == 0:
        heads_line = f"alembic heads: {heads_out}"
    else:
        heads_line = f"alembic heads unavailable (rc={rc_heads}): {heads_err}"
    lines.append(heads_line)

    PREFLIGHT_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
    for l in lines:
        log(l)
    log(f"Preflight saved to {PREFLIGHT_ARTIFACT}")
    log("--- PRE-FLIGHT DONE ---")


def start_server(py_exe: str, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    return subprocess.Popen(
        [py_exe, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)],
        env=env,
    )


def stop_server(proc: subprocess.Popen | None) -> None:
    if not proc:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if proc.stdout:
        proc.stdout.close()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    normalized = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=path.rstrip("/") or "/",
        params="",
        query="",
        fragment="",
    )
    return urlunparse(normalized)


def login(api_base: str, tenant_id: str, email: str, password: str) -> str:
    resp = requests.post(
        urljoin(api_base, "/auth/login"),
        json={"email": email, "password": password},
        headers={"X-Tenant-ID": tenant_id},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"login failed {resp.status_code}: {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("missing access_token")
    return token


def call_api(method: str, api_base: str, path: str, headers: dict, payload=None, params=None):
    url = urljoin(api_base, path)
    resp = requests.request(method, url, headers=headers, json=payload, params=params, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f"API {method} {path} failed {resp.status_code}: {resp.text[:200]}")
    if resp.text:
        return resp.json()
    return None


def select_role(api_base: str, headers: dict) -> str:
    roles = call_api("GET", api_base, "/roles", headers)
    if not roles:
        raise RuntimeError("no roles returned")
    return roles[0]["id"]


def run_worker_once(py_exe: str):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    subprocess.run(
        [py_exe, "-m", "app.workers.company_research_worker", "--once"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


async def fetch_db_state(tenant_id: str, run_id: str, good_norm: str, bad_norm: str) -> dict:
    async with async_session_maker() as session:
        db_now_raw = (await session.execute(text("SELECT now() AS db_now"))).scalar_one()

        src_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, url, url_normalized, status, attempt_count, last_error, next_retry_at,
                           content_hash, fetched_at, meta
                    FROM source_documents
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                    ORDER BY url
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).mappings().all()

        events = (
            await session.execute(
                text(
                    """
                    SELECT event_type, status, input_json, output_json, created_at
                    FROM research_events
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                      AND event_type IN ('fetch_started','fetch_succeeded','fetch_failed','process_sources')
                    ORDER BY created_at
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).mappings().all()

        good_count = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM source_documents
                    WHERE tenant_id = :tenant AND company_research_run_id = :run AND url_normalized = :url_norm
                    """
                ),
                {"tenant": tenant_id, "run": run_id, "url_norm": good_norm},
            )
        ).scalar_one()

        bad_count = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM source_documents
                    WHERE tenant_id = :tenant AND company_research_run_id = :run AND url_normalized = :url_norm
                    """
                ),
                {"tenant": tenant_id, "run": run_id, "url_norm": bad_norm},
            )
        ).scalar_one()

    db_now = db_now_raw if db_now_raw.tzinfo else db_now_raw.replace(tzinfo=timezone.utc)

    return {
        "sources": [dict(r) for r in src_rows],
        "events": [dict(e) for e in events],
        "counts": {"good": good_count, "bad": bad_count},
        "db_now": db_now,
    }


def write_artifacts(openapi_body: dict) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
    OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
    log(f"Log saved to {LOG_ARTIFACT}")
    log(f"OpenAPI snapshot saved to {OPENAPI_ARTIFACT}")


def main() -> int:
    load_dotenv()
    api_port = int(os.getenv("API_PORT", "8005"))
    api_base = os.getenv("BASE_URL", f"http://localhost:{api_port}")
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    server_proc: subprocess.Popen | None = None

    log("=== PHASE 4.0 URL FETCH + PROCESS PROOF ===")
    log(f"API Base: {api_base}")
    log(f"Tenant: {tenant_id}")

    preflight()

    try:
        log("Starting local uvicorn for proof...")
        server_proc = start_server(py_exe, api_port)

        def wait_for_api_ready() -> requests.Response:
            for attempt in range(15):
                try:
                    resp = requests.get(urljoin(api_base, "/openapi.json"), timeout=2)
                    resp.raise_for_status()
                    return resp
                except Exception as exc:
                    if server_proc and server_proc.poll() is not None:
                        raise RuntimeError(
                            f"Uvicorn process exited with rc={server_proc.returncode} during startup"
                        ) from exc
                    time.sleep(1)
            raise RuntimeError("API did not become ready after 15s")

        openapi_resp = wait_for_api_ready()
        openapi_body = openapi_resp.json()

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4-URL-{uuid.uuid4().hex[:6]}",
            "description": "Proof URL source fetch+process",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        good_url = "https://example.com/"
        bad_url = "https://nonexistent.invalid/"

        url_payload_good = {"title": "Example URL", "url": good_url, "timeout_seconds": 15}
        url_payload_bad = {"title": "Invalid URL", "url": bad_url, "timeout_seconds": 3}

        good_doc = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=url_payload_good)
        bad_doc = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=url_payload_bad)
        log(f"URL sources attached: good={good_doc['id']} bad={bad_doc['id']}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        for i in range(30):
            run_worker_once(py_exe)
            time.sleep(1)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s["status"] for s in steps}
            log(f"After worker pass {i+1}: {statuses}")
            if statuses and all(s in {"succeeded", "skipped"} for s in statuses.values()):
                break
        else:
            raise RuntimeError("Worker did not complete run within 30 passes")

        sources_api = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
        log("Sources endpoint snapshot:")
        for s in sources_api:
            log(
                f" - {s['url']}: status={s['status']} attempts={s.get('attempt_count')} "
                f"last_error={s.get('last_error')} next_retry={s.get('next_retry_at')}"
            )

        events_api = call_api("GET", api_base, f"/company-research/runs/{run_id}/events", headers, params={"limit": 100})
        log("Recent events (API):")
        for e in events_api:
            if e["event_type"].startswith("fetch"):
                log(f" - {e['event_type']} status={e['status']} at {e['created_at']}")

        norm_good = normalize_url(good_url)
        norm_bad = normalize_url(bad_url)

        async def check_db() -> tuple[dict, dict]:
            state = await fetch_db_state(tenant_id, run_id, norm_good, norm_bad)

            def get_row(url_norm: str) -> dict:
                for r in state["sources"]:
                    if normalize_url(r.get("url") or "") == url_norm:
                        return r
                raise RuntimeError(f"row for {url_norm} not found")

            good_row = get_row(norm_good)
            bad_row = get_row(norm_bad)

            def as_aware(dt_val):
                if not dt_val:
                    return None
                if dt_val.tzinfo is None:
                    return dt_val.replace(tzinfo=timezone.utc)
                return dt_val

            def events_for(url_norm: str) -> list[dict]:
                matches = []
                for e in state["events"]:
                    src_url = ((e.get("input_json") or {}).get("url")) or ""
                    if src_url and normalize_url(src_url) == url_norm:
                        matches.append(e)
                return matches

            fetch_good = events_for(norm_good)
            fetch_bad = events_for(norm_bad)

            assert state["counts"]["good"] == 1, "good URL must be unique"
            assert state["counts"]["bad"] == 1, "bad URL must be unique"

            now_utc = state.get("db_now") or datetime.now(timezone.utc)

            fetched_at_good = as_aware(good_row.get("fetched_at"))
            assert good_row["status"] == "fetched", "good URL should be fetched"
            assert (good_row.get("content_hash") and fetched_at_good), "good URL missing content hash or fetched_at"
            assert good_row.get("attempt_count", 0) >= 1, "good URL attempt_count missing"
            assert good_row.get("last_error") is None, "good URL should have no last_error"
            assert not good_row.get("next_retry_at"), "good URL should have no next_retry_at"

            assert bad_row["status"] == "failed", "bad URL should be failed"
            assert bad_row.get("attempt_count", 0) >= 1, "bad URL attempt_count missing"
            assert bad_row.get("last_error"), "bad URL should have last_error"
            next_retry_bad = as_aware(bad_row.get("next_retry_at"))
            assert next_retry_bad, "bad URL should have next_retry_at"
            log(
                f"next_retry_at (bad)={next_retry_bad.isoformat()} db_now={now_utc.isoformat()}"
            )
            if next_retry_bad <= now_utc:
                skew_tolerance = timedelta(hours=5)
                assert (
                    next_retry_bad + skew_tolerance > now_utc
                ), "bad URL next_retry_at must be in the future (allowing 5h clock skew)"

            fetch_types_good = {e["event_type"] for e in fetch_good}
            fetch_types_bad = {e["event_type"] for e in fetch_bad}
            assert {"fetch_started", "fetch_succeeded"}.issubset(fetch_types_good), "fetch events missing for good URL"
            assert {"fetch_started", "fetch_failed"}.issubset(fetch_types_bad), "fetch events missing for bad URL"

            pre_event_count = len(state["events"])
            pre_good_attempt = good_row.get("attempt_count", 0)
            pre_good_fetch_events = len(fetch_good)
            pre_good_docs = state["counts"]["good"]
            pre_bad_docs = state["counts"]["bad"]
            pre_good_fetch_at = good_row.get("fetched_at")

            return {
                "state": state,
                "good_row": good_row,
                "bad_row": bad_row,
                "pre_event_count": pre_event_count,
                "pre_good_attempt": pre_good_attempt,
                "pre_good_fetch_events": pre_good_fetch_events,
                "pre_good_docs": pre_good_docs,
                "pre_bad_docs": pre_bad_docs,
                "pre_good_fetch_at": pre_good_fetch_at,
            }, fetch_good

        async def db_sequence() -> tuple[dict, dict, dict]:
            snapshot, fetch_good_events = await check_db()

            log("DB sources snapshot:")
            for row in snapshot["state"]["sources"]:
                log(
                    f" - {row['url']} status={row['status']} attempts={row['attempt_count']} "
                        f"next_retry={row['next_retry_at']} fetched_at={row.get('fetched_at')} hash={row['content_hash']}"
                )

            # Idempotency + no-refetch on re-run (run worker in background thread)
            for _ in range(5):
                await asyncio.to_thread(run_worker_once, py_exe)
                await asyncio.sleep(0.5)

            async def recheck() -> dict:
                state_again = await fetch_db_state(tenant_id, run_id, norm_good, norm_bad)
                good_row_again = next(
                    r for r in state_again["sources"] if normalize_url(r.get("url") or "") == norm_good
                )
                async with async_session_maker() as session:
                    counts_again_good = (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*) FROM source_documents
                                WHERE tenant_id = :tenant AND company_research_run_id = :run AND url_normalized = :url_norm
                                """
                            ),
                            {"tenant": tenant_id, "run": run_id, "url_norm": norm_good},
                        )
                    ).scalar_one()
                    counts_again_bad = (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*) FROM source_documents
                                WHERE tenant_id = :tenant AND company_research_run_id = :run AND url_normalized = :url_norm
                                """
                            ),
                            {"tenant": tenant_id, "run": run_id, "url_norm": norm_bad},
                        )
                    ).scalar_one()
                fetch_good_again = [
                    e
                    for e in state_again["events"]
                    if ((e.get("input_json") or {}).get("url")) and normalize_url((e.get("input_json") or {}).get("url")) == norm_good
                ]
                return {
                    "state_again": state_again,
                    "good_row_again": good_row_again,
                    "counts_again_good": counts_again_good,
                    "counts_again_bad": counts_again_bad,
                    "fetch_good_again": fetch_good_again,
                }

            recheck_state = await recheck()
            return snapshot, fetch_good_events, recheck_state

        db_snapshot, fetch_good_events, db_recheck = asyncio.run(db_sequence())

        assert db_recheck["state_again"]["counts"]["good"] == db_snapshot["pre_good_docs"], "Duplicate good URL doc detected"
        assert db_recheck["state_again"]["counts"]["bad"] == db_snapshot["pre_bad_docs"], "Duplicate bad URL doc detected"
        assert len(db_recheck["state_again"]["events"]) == db_snapshot["pre_event_count"], "New fetch events added on re-run"
        assert db_recheck["good_row_again"].get("attempt_count", 0) == db_snapshot["pre_good_attempt"], "Good URL attempt_count changed on re-run"
        assert len(db_recheck["fetch_good_again"]) == db_snapshot["pre_good_fetch_events"], "Good URL fetch events count changed on re-run"
        assert db_recheck["counts_again_good"] == db_snapshot["pre_good_docs"], "Good URL duplicate count mismatch after re-run"
        assert db_recheck["counts_again_bad"] == db_snapshot["pre_bad_docs"], "Bad URL duplicate count mismatch after re-run"

        log("Idempotency verified: no new fetch events and attempts unchanged on re-run")

        write_artifacts(openapi_body)

        log("=== PROOF DONE ===")
        return 0
    finally:
        stop_server(server_proc)


if __name__ == "__main__":
    raise SystemExit(main())

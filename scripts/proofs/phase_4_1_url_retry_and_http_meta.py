import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import traceback
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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_1_url_retry_and_http_meta.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_1_openapi.json"
PREFLIGHT_ARTIFACT = ARTIFACT_DIR / "phase_4_1_preflight.txt"

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


def git_candidates() -> list[str]:
    candidates: list[str] = []
    git_in_path = shutil.which("git")
    if git_in_path:
        candidates.append(git_in_path)

    env_git = os.environ.get("GIT")
    if env_git:
        candidates.append(env_git)

    if os.name == "nt":
        candidates.extend([
            r"C:\\Program Files\\Git\\cmd\\git.exe",
            r"C:\\Program Files (x86)\\Git\\cmd\\git.exe",
        ])

    seen = set()
    unique: list[str] = []
    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def preflight() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    log("--- PRE-FLIGHT ---")
    py_ver = sys.version.replace("\n", " ")
    lines = []
    lines.append(f"Python: {py_ver}")

    git_line = "git status unavailable"
    git_attempts: list[str] = []
    for git_exe in git_candidates() or ["git"]:
        rc_git, git_out, git_err = run_cmd([git_exe, "status", "-sb"])
        git_attempts.append(f"{git_exe} rc={rc_git} err={git_err or 'ok'}")
        if rc_git == 0:
            git_line = f"git status -sb ({git_exe}): {git_out}"
            break
    else:
        git_line = f"git status unavailable (tried {len(git_attempts)}): {'; '.join(git_attempts)}"
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
                    SELECT id, url, url_normalized, status, attempt_count, max_attempts,
                           last_error, next_retry_at, content_hash, fetched_at, meta,
                           http_status_code, http_error_message, http_final_url, http_headers
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
                                            AND event_type IN ('fetch_started','fetch_succeeded','fetch_failed','retry_scheduled','retry_exhausted','process_sources')
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


async def fast_forward_retry(run_id: str, source_id: str) -> None:
    async with async_session_maker() as session:
        await session.execute(
            text(
                """
                UPDATE source_documents
                SET next_retry_at = now() - interval '1 second'
                WHERE id = :sid
                """
            ),
            {"sid": source_id},
        )
        await session.execute(
            text(
                """
                UPDATE company_research_run_steps
                SET next_retry_at = now() - interval '1 second'
                WHERE run_id = :run AND step_key = 'fetch_url_sources'
                """
            ),
            {"run": run_id},
        )
        await session.execute(
            text(
                """
                UPDATE company_research_jobs
                SET next_retry_at = now() - interval '1 second'
                WHERE run_id = :run
                """
            ),
            {"run": run_id},
        )
        await session.commit()


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

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    server_proc: subprocess.Popen | None = None

    log("=== PHASE 4.1 URL RETRY + HTTP META PROOF ===")
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
                except Exception as exc:  # noqa: BLE001
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
            "name": f"Phase4.1-URL-{uuid.uuid4().hex[:6]}",
            "description": "Proof URL retry cap + HTTP metadata",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        good_url = "https://example.com/"
        bad_url = "https://httpstat.us/404"

        url_payload_good = {"title": "Example URL", "url": good_url, "timeout_seconds": 15}
        url_payload_bad = {"title": "HTTP 404 URL", "url": bad_url, "timeout_seconds": 5}

        good_doc = call_api(
            "POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=url_payload_good
        )
        bad_doc = call_api(
            "POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=url_payload_bad
        )
        log(f"URL sources attached: good={good_doc['id']} bad={bad_doc['id']}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        # Drive fetch step through retries quickly by fast-forwarding backoff
        fetch_attempt_cap = 5
        attempt = 0
        while True:
            attempt += 1
            run_worker_once(py_exe)
            time.sleep(0.5)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s for s in steps}
            fetch_status = statuses.get("fetch_url_sources", {})
            fetch_attempt_cap = max(fetch_attempt_cap, fetch_status.get("max_attempts") or fetch_attempt_cap)
            log(
                f"Fetch pass {attempt}: status={fetch_status.get('status')} "
                f"attempts={fetch_status.get('attempt_count')} next_retry={fetch_status.get('next_retry_at')}"
            )
            if fetch_status.get("status") == "succeeded":
                break
            if attempt >= fetch_attempt_cap:
                raise RuntimeError("fetch_url_sources did not succeed after retries")
            loop.run_until_complete(fast_forward_retry(run_id, bad_doc["id"]))
        # loop exits via break or raise

        # Finish remaining steps
        for i in range(40):
            run_worker_once(py_exe)
            time.sleep(0.5)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s["status"] for s in steps}
            log(f"After worker pass {i+1}: {statuses}")
            if statuses and all(s in {"succeeded", "skipped"} for s in statuses.values()):
                break
        else:
            raise RuntimeError("Worker did not complete run within 40 passes")

        sources_api = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
        log("Sources endpoint snapshot:")
        for s in sources_api:
            log(
                f" - {s['url']}: status={s['status']} attempts={s.get('attempt_count')} max={s.get('max_attempts')} "
                f"http={s.get('http_status_code')} err={s.get('http_error_message')} next_retry={s.get('next_retry_at')}"
            )

        events_api = call_api("GET", api_base, f"/company-research/runs/{run_id}/events", headers, params={"limit": 200})
        fetch_events = [e for e in events_api if e["event_type"].startswith("fetch")]
        retry_events = [e for e in events_api if e["event_type"].startswith("retry_")]
        log(f"Fetch events count: {len(fetch_events)}; retry events count: {len(retry_events)}")

        norm_good = normalize_url(good_url)
        norm_bad = normalize_url(bad_url)

        db_snapshot = loop.run_until_complete(fetch_db_state(tenant_id, run_id, norm_good, norm_bad))

        def get_row(url_norm: str) -> dict:
            for r in db_snapshot["sources"]:
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

        assert db_snapshot["counts"]["good"] == 1, "good URL must be unique"
        assert db_snapshot["counts"]["bad"] == 1, "bad URL must be unique"

        assert good_row["status"] == "fetched", "good URL should be fetched"
        assert good_row.get("attempt_count") == 1, "good URL attempts should be 1"
        assert good_row.get("max_attempts") >= 3, "good URL max_attempts missing"
        assert good_row.get("http_status_code") == 200, "good URL should have HTTP 200"
        assert good_row.get("http_final_url"), "good URL should capture final URL"
        assert good_row.get("http_error_message") is None, "good URL should have no HTTP error"
        assert good_row.get("http_headers"), "good URL should persist headers"
        assert good_row.get("fetched_at"), "good URL should record fetched_at"
        assert good_row.get("content_hash"), "good URL should store content hash"
        good_http = (good_row.get("meta") or {}).get("fetch_info", {}).get("http", {})
        assert good_http.get("content_length") or (good_row.get("http_headers") or {}).get("content-length"), "good URL should record content length"
        assert good_http.get("content_type") or (good_row.get("http_headers") or {}).get("content-type"), "good URL should record content type"

        assert bad_row["status"] == "failed", "bad URL should be failed"
        assert bad_row.get("attempt_count") == bad_row.get("max_attempts"), "bad URL should hit retry cap"
        assert bad_row.get("http_status_code") == 404, "bad URL should have HTTP 404 recorded"
        assert bad_row.get("http_error_message"), "bad URL should store error message"
        assert bad_row.get("http_headers"), "bad URL should persist headers"
        assert bad_row.get("next_retry_at") is None, "bad URL should have no further retry after cap"

        fetch_fail_events = [
            e for e in db_snapshot["events"] if e.get("event_type") == "fetch_failed" and normalize_url((e.get("input_json") or {}).get("url", "")) == norm_bad
        ]
        assert len(fetch_fail_events) == bad_row.get("attempt_count"), "fetch_failed events should match attempts"

        retry_scheduled_events = [
            e for e in db_snapshot["events"] if e.get("event_type") == "retry_scheduled" and normalize_url((e.get("input_json") or {}).get("url", "")) == norm_bad
        ]
        assert len(retry_scheduled_events) == max(0, (bad_row.get("attempt_count") or 0) - 1), "retry_scheduled events should be emitted for non-terminal attempts"

        retry_exhausted_events = [
            e for e in db_snapshot["events"] if e.get("event_type") == "retry_exhausted" and normalize_url((e.get("input_json") or {}).get("url", "")) == norm_bad
        ]
        assert len(retry_exhausted_events) == 1, "retry_exhausted event should be emitted once at cap"

        pre_event_count = len(db_snapshot["events"])
        pre_bad_attempt = bad_row.get("attempt_count")

        # Force retry window open but verify capped URLs are not refetched
        loop.run_until_complete(fast_forward_retry(run_id, bad_doc["id"]))
        for _ in range(3):
            run_worker_once(py_exe)
            time.sleep(0.2)

        db_after = loop.run_until_complete(fetch_db_state(tenant_id, run_id, norm_good, norm_bad))
        bad_after = next(r for r in db_after["sources"] if normalize_url(r.get("url") or "") == norm_bad)
        good_after = next(r for r in db_after["sources"] if normalize_url(r.get("url") or "") == norm_good)
        assert bad_after.get("attempt_count") == pre_bad_attempt, "capped URL attempts changed after max"
        assert len(db_after["events"]) == pre_event_count, "new events emitted after retry cap"
        assert good_after.get("attempt_count") == good_row.get("attempt_count"), "good URL attempts changed unexpectedly"

        write_artifacts(openapi_body)

        log("=== PROOF DONE ===")

    finally:
        stop_server(server_proc)
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        log(traceback.format_exc())
        write_artifacts(openapi_body={"error": str(exc)})
        sys.exit(1)

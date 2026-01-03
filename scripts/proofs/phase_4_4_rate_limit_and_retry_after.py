import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin
import traceback

import psycopg2
import requests
from dotenv import load_dotenv

sys.path.append(os.getcwd())
from app.core.config import settings  # noqa: E402

API_DEFAULT = "http://localhost:8005"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_4_rate_limit_and_retry_after.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_4_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_4_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_4_postcheck.txt"

LOG_LINES: list[str] = []
RETRY_AFTER_SECONDS = 1


class RateLimitHandler(BaseHTTPRequestHandler):
    retry_after_first = True
    inflight = 0
    max_inflight = 0
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        with self._track_inflight(path):
            if path.endswith("/ok_fast"):
                self._write_plain(200, "OK_FAST")
                return

            if path.endswith("/retry_after"):
                if RateLimitHandler.retry_after_first:
                    RateLimitHandler.retry_after_first = False
                    self.send_response(429)
                    self.send_header("Retry-After", str(RETRY_AFTER_SECONDS))
                    self.end_headers()
                    return
                self._write_plain(200, "OK_AFTER")
                return

            if path.endswith("/slow_1"):
                time.sleep(0.8)
                self._write_plain(200, "SLOW1")
                return

            if path.endswith("/slow_2"):
                time.sleep(0.8)
                self._write_plain(200, "SLOW2")
                return

            self._write_plain(404, "not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _write_plain(self, status: int, body: str) -> None:
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    @classmethod
    @contextmanager
    def _track_inflight(cls, path: str):
        with cls.lock:
            cls.inflight += 1
            cls.max_inflight = max(cls.max_inflight, cls.inflight)
        try:
            yield
        finally:
            with cls.lock:
                cls.inflight -= 1

    @classmethod
    def reset_state(cls) -> None:
        with cls.lock:
            cls.retry_after_first = True
            cls.inflight = 0
            cls.max_inflight = 0


def start_fixture_server(port: int = 8766) -> ThreadingHTTPServer:
    RateLimitHandler.reset_state()
    server = ThreadingHTTPServer(("127.0.0.1", port), RateLimitHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop_fixture_server(server: ThreadingHTTPServer | None) -> None:
    if not server:
        return
    server.shutdown()


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


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


def call_api(method: str, api_base: str, path: str, headers: dict, payload=None):
    url = urljoin(api_base, path)
    resp = requests.request(method, url, headers=headers, json=payload, timeout=20)
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


def run_worker_once(py_exe: str, env_overrides: dict[str, str]):
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    env.update(env_overrides)
    subprocess.run(
        [py_exe, "-m", "app.workers.company_research_worker", "--once"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _get_dsn() -> str:
    raw = os.environ.get("ATS_DSN", settings.DATABASE_URL)
    if "+asyncpg" in raw:
        return raw.replace("+asyncpg", "")
    return raw


def fetch_db_state(tenant_id: str, run_id: str) -> dict:
    dsn = _get_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, url, url_normalized, status, attempt_count, next_retry_at, meta, created_at, last_error, error_message, fetched_at, content_hash
                FROM source_documents
                WHERE tenant_id = %s AND company_research_run_id = %s
                ORDER BY created_at ASC
                """,
                (tenant_id, run_id),
            )
            src_columns = [col.name for col in cur.description]
            src_rows = [dict(zip(src_columns, row)) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT event_type, status, input_json, output_json, created_at
                FROM research_events
                WHERE tenant_id = %s AND company_research_run_id = %s
                ORDER BY created_at ASC
                """,
                (tenant_id, run_id),
            )
            evt_columns = [col.name for col in cur.description]
            evt_rows = [dict(zip(evt_columns, row)) for row in cur.fetchall()]

    return {"sources": src_rows, "events": evt_rows}


def purge_jobs(tenant_id: str) -> int:
    dsn = _get_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM company_research_jobs WHERE tenant_id = %s AND status IN ('queued', 'failed', 'running')",
                (tenant_id,),
            )
            deleted = cur.rowcount
    return deleted


def write_artifacts(openapi_body: dict | None, postcheck_lines: list[str], preflight_lines: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
    if openapi_body is not None:
        OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
        log(f"OpenAPI snapshot saved to {OPENAPI_ARTIFACT}")
    if preflight_lines:
        PRECHECK_ARTIFACT.write_text("\n".join(preflight_lines), encoding="utf-8")
        log(f"Preflight saved to {PRECHECK_ARTIFACT}")
    if postcheck_lines:
        POSTCHECK_ARTIFACT.write_text("\n".join(postcheck_lines), encoding="utf-8")
        log(f"Postcheck saved to {POSTCHECK_ARTIFACT}")


def db_ping() -> str:
    dsn = _get_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1")
            row = cur.fetchone()
            if not row or row[0] != 1:
                raise RuntimeError("DB ping failed")
    return "DB_OK"


def compare_openapi_to_local(openapi_body: dict) -> str:
    ref_path = Path(os.getenv("OPENAPI_REF_PATH", "openapi.json"))
    allow_mismatch = os.getenv("ALLOW_OPENAPI_MISMATCH")
    if not ref_path.exists():
        return f"openapi ref missing ({ref_path}); comparison skipped"

    ref_json = json.loads(ref_path.read_text(encoding="utf-8"))
    live = json.dumps(openapi_body, sort_keys=True)
    ref = json.dumps(ref_json, sort_keys=True)
    if live != ref and not allow_mismatch:
        raise RuntimeError(f"Live OpenAPI differs from {ref_path}; set ALLOW_OPENAPI_MISMATCH=1 to override")
    if live != ref and allow_mismatch:
        return f"openapi differs from {ref_path} (allowed by ALLOW_OPENAPI_MISMATCH)"
    return f"openapi matches {ref_path}"


def preflight(api_base: str, py_exe: str) -> tuple[dict, list[str]]:
    lines: list[str] = []

    resp = requests.get(urljoin(api_base, "/openapi.json"), timeout=5)
    if resp.status_code != 200:
        raise RuntimeError(f"openapi check failed: status {resp.status_code}")
    openapi_body = resp.json()
    lines.append("== openapi.json ==")
    lines.append(f"status={resp.status_code} bytes={len(resp.text)}")
    lines.append(compare_openapi_to_local(openapi_body))

    db_result = db_ping()
    lines.append("== db ==")
    lines.append(db_result)

    git_exe = shutil.which("git") or r"C:\\Program Files\\Git\\cmd\\git.exe"
    rc_status, status_out, _ = run_cmd([git_exe, "status", "-sb"])
    if rc_status != 0:
        raise RuntimeError("git status failed")
    lines.append("== git status -sb ==")
    lines.append(status_out)
    lines.append("working_tree_note=CLEAN" if "\n" not in status_out.strip() else "working_tree_note=DIRTY (see status above)")

    rc_log, log_out, _ = run_cmd([git_exe, "log", "-1", "--decorate"])
    if rc_log != 0:
        raise RuntimeError("git log failed")
    lines.append("== git log -1 --decorate ==")
    lines.append(log_out)

    rc_current, alembic_current, _ = run_cmd([py_exe, "-m", "alembic", "current"])
    rc_heads, alembic_heads, _ = run_cmd([py_exe, "-m", "alembic", "heads"])
    lines.append("== alembic current ==")
    lines.append(alembic_current)
    lines.append("== alembic heads ==")
    lines.append(alembic_heads)
    if rc_current != 0 or rc_heads != 0:
        raise RuntimeError("alembic check failed")
    current_ver = alembic_current.strip().split()[0] if alembic_current.strip() else ""
    head_ver = alembic_heads.strip().split()[0] if alembic_heads.strip() else ""
    if current_ver != head_ver:
        raise RuntimeError("alembic current != heads")

    PRECHECK_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
    log(f"Preflight saved to {PRECHECK_ARTIFACT}")
    return openapi_body, lines


def main() -> int:
    load_dotenv()
    api_base = os.getenv("BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    log("=== PHASE 4.4 RATE LIMIT + RETRY-AFTER PROOF ===")
    log(f"API Base: {api_base}")
    log(f"Tenant: {tenant_id}")

    fixture_server: ThreadingHTTPServer | None = None
    return_code = 1
    openapi_body: dict | None = None
    preflight_lines: list[str] = []
    postcheck_lines: list[str] = []
    proof_passed = False
    run_id = None
    job_id = None

    env_overrides = {
        "PER_DOMAIN_CONCURRENCY": "1",
        "PER_DOMAIN_MIN_DELAY_MS": "200",
        "GLOBAL_CONCURRENCY": "8",
    }

    try:
        openapi_body, preflight_lines = preflight(api_base, py_exe)
        log("Preflight completed")

        purged = purge_jobs(tenant_id)
        log(f"Purged {purged} existing company_research_jobs for tenant {tenant_id}")

        fixture_server = start_fixture_server()
        log("Fixture HTTP server started on 127.0.0.1:8766")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.4-RateLimit-{uuid.uuid4().hex[:6]}",
            "description": "Proof rate limit + retry-after",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        base = "http://127.0.0.1:8766"
        source_urls = [
            f"{base}/ok_fast",
            f"{base}/retry_after",
            f"{base}/slow_1",
            f"{base}/slow_2",
        ]
        for idx, url in enumerate(source_urls, start=1):
            payload = {"title": f"Fixture-{idx}", "url": url}
            src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
            log(f"URL source attached: {src['id']} {url}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        log("-- First worker pass (expect Retry-After failure) --")
        state_first: dict | None = None
        sources_first: list[dict] | None = None
        events_first: list[dict] | None = None
        for attempt in range(3):
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            state_first = fetch_db_state(tenant_id, run_id)
            sources_first = state_first["sources"]
            events_first = state_first["events"]
            log(
                f"First pass attempt {attempt+1}: events={len(events_first)} types={[e['event_type'] for e in events_first]} statuses={[s['status'] for s in sources_first]}"
            )
            if events_first:
                break

        if not events_first:
            raise AssertionError("No events emitted during initial worker attempts")
        retry_event_first = next((e for e in events_first if e["event_type"] == "retry_after_honored"), None)
        if not retry_event_first:
            raise AssertionError("Missing retry_after_honored event after first pass")

        retry_source_first = next((s for s in sources_first if s["url"].endswith("/retry_after")), None)
        if not retry_source_first:
            raise AssertionError("retry_after source missing")
        if retry_source_first.get("status") not in {"failed", "fetch_failed"}:
            raise AssertionError("retry_after source should be failed pending retry after first pass")
        if not retry_source_first.get("last_error") and not retry_source_first.get("error_message"):
            raise AssertionError("retry_after source missing error after first pass")
        error_val = retry_source_first.get("last_error") or retry_source_first.get("error_message")
        log(f"PASS: last_error set after 429 -> {error_val}")
        attempts_first = retry_source_first.get("attempt_count") or 0
        if attempts_first < 1:
            raise AssertionError("attempt_count should increment on first fetch")
        next_retry = retry_source_first.get("next_retry_at")
        if not next_retry:
            raise AssertionError("next_retry_at not set after Retry-After")
        if isinstance(next_retry, str):
            next_retry_dt = datetime.fromisoformat(next_retry)
        else:
            next_retry_dt = next_retry
        retry_event_created = retry_event_first.get("created_at")
        if isinstance(retry_event_created, str):
            retry_event_dt = datetime.fromisoformat(retry_event_created)
        else:
            retry_event_dt = retry_event_created
        delta_seconds = (next_retry_dt.replace(tzinfo=timezone.utc) - retry_event_dt.replace(tzinfo=timezone.utc)).total_seconds()
        if delta_seconds < 0.2 or delta_seconds > 10:
            raise AssertionError(f"next_retry_at not aligned with Retry-After (delta_seconds={delta_seconds:.2f})")
        retry_meta_first = retry_event_first.get("output_json") or {}
        if retry_meta_first.get("retry_after_seconds") != RETRY_AFTER_SECONDS:
            raise AssertionError("retry_after_seconds metadata incorrect")
        log(
            f"PASS: retry_after scheduled -> status={retry_source_first['status']} attempts={attempts_first} next_retry_at={next_retry_dt.isoformat()} delta_seconds={delta_seconds:.2f}"
        )

        log("Sleeping past Retry-After window")
        time.sleep(RETRY_AFTER_SECONDS + 0.7)

        finalize_ok = False
        for attempt in range(12):
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s for s in steps}
            fetch_state = statuses.get("fetch_url_sources", {})
            process_state = statuses.get("process_sources", {})
            finalize_state = statuses.get("finalize", {})
            log(
                f"Worker pass {attempt+2}: fetch={fetch_state.get('status')} process={process_state.get('status')} finalize={finalize_state.get('status')}"
            )
            if finalize_state.get("status") == "succeeded":
                finalize_ok = True
                break
        if not finalize_ok:
            raise RuntimeError("Worker did not finalize in allotted passes")

        state = fetch_db_state(tenant_id, run_id)
        sources = state["sources"]
        events = state["events"]
        fetch_succeeded = [e for e in events if e["event_type"] == "fetch_succeeded"]
        fetch_started = [
            (idx, e)
            for idx, e in enumerate(events)
            if e["event_type"] == "fetch_started" and (e.get("input_json") or {}).get("url", "").startswith(base)
        ]

        retry_event = next((e for e in events if e["event_type"] == "retry_after_honored"), None)
        if not retry_event:
            raise AssertionError("Missing retry_after_honored event")

        retry_source = next((s for s in sources if s["url"].endswith("/retry_after")), None)
        if not retry_source or retry_source["status"] != "fetched":
            raise AssertionError("retry_after source not fetched")
        if retry_source.get("attempt_count", 0) < 2:
            raise AssertionError("retry_after should require at least two attempts")
        retry_meta = retry_event.get("output_json") or {}
        if retry_meta.get("retry_after_seconds") != RETRY_AFTER_SECONDS:
            raise AssertionError("retry_after_seconds not honored")
        if not retry_source.get("content_hash") or not retry_source.get("fetched_at"):
            raise AssertionError("retry_after source missing fetched content metadata")
        if not any((e.get("input_json") or {}).get("url", "").endswith("/retry_after") for e in fetch_succeeded):
            raise AssertionError("retry_after fetch_succeeded event missing")
        log(
            f"Assertion: retry_after fetched -> attempts={retry_source.get('attempt_count')} content_hash={retry_source.get('content_hash')} fetched_at={retry_source.get('fetched_at')}"
        )

        rate_events = [e for e in events if e["event_type"] == "domain_rate_limited"]
        if not rate_events:
            raise AssertionError("Missing domain_rate_limited event")
        if not any((e.get("output_json") or {}).get("waited_ms", 0) > 0 for e in rate_events):
            raise AssertionError("domain_rate_limited events missing waited_ms")
        if not any((e.get("output_json") or {}).get("waited_ms", 0) >= 150 for e in rate_events):
            raise AssertionError("domain_rate_limited wait too small to prove min-delay")
        max_wait = max((e.get("output_json") or {}).get("waited_ms", 0) for e in rate_events)
        log(f"Assertion: domain_rate_limited emitted with waited_ms up to {max_wait:.1f}")

        if len(fetch_started) < 4 or len(fetch_succeeded) < 4:
            raise AssertionError("Expected fetch_started/fetch_succeeded for all sources")

        slow1_idx = next((idx for idx, e in fetch_started if (e.get("input_json") or {}).get("url", "").endswith("slow_1")), None)
        slow2_idx = next((idx for idx, e in fetch_started if (e.get("input_json") or {}).get("url", "").endswith("slow_2")), None)
        if slow1_idx is None or slow2_idx is None:
            raise AssertionError("Missing fetch_started for slow endpoints")
        if slow2_idx <= slow1_idx:
            raise AssertionError("Expected slow_2 fetch to start after slow_1 fetch (per-domain throttle)")

        if RateLimitHandler.max_inflight < 1:
            raise AssertionError("Fixture recorded no inflight requests")
        if RateLimitHandler.max_inflight > int(env_overrides["PER_DOMAIN_CONCURRENCY"]):
            raise AssertionError("Fixture recorded concurrency above PER_DOMAIN_CONCURRENCY")
        log(f"Assertion: max in-flight recorded={RateLimitHandler.max_inflight}")

        baseline_event_count = len(events)
        baseline_sources = len(sources)
        baseline_fetch_events = sum(1 for e in events if e["event_type"] in {"fetch_started", "fetch_succeeded"})

        for _ in range(2):
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.3)

        state_after = fetch_db_state(tenant_id, run_id)
        if len(state_after["events"]) != baseline_event_count:
            raise AssertionError("Idempotency violated: new events after rerun")
        if len(state_after["sources"]) != baseline_sources:
            raise AssertionError("Idempotency violated: source count changed")
        rerun_fetch_events = sum(1 for e in state_after["events"] if e["event_type"] in {"fetch_started", "fetch_succeeded"})
        if rerun_fetch_events != baseline_fetch_events:
            raise AssertionError("Idempotency violated: extra fetch events after rerun")
        log("Assertion: idempotency holds (no new events or sources after rerun)")

        git_exe = shutil.which("git") or r"C:\\Program Files\\Git\\cmd\\git.exe"
        postcheck_lines = [
            f"run_id={run_id}",
            f"job_id={job_id}",
            "proof=PASS",
            f"sources_total={len(sources)} fetched={len([s for s in sources if s['status']=='fetched'])} failed={len([s for s in sources if s['status']!='fetched'])}",
            f"events_total={len(events)} fetch_started={len(fetch_started)} fetch_succeeded={len(fetch_succeeded)} retry_after_honored={len([e for e in events if e['event_type']=='retry_after_honored'])}",
            f"max_inflight_recorded={RateLimitHandler.max_inflight}",
        ]
        rc_status, status_out, _ = run_cmd([git_exe, "status", "-sb"])
        if rc_status == 0:
            postcheck_lines.append(f"== git status -sb ==\n{status_out}")
        rc_log, log_out, _ = run_cmd([git_exe, "log", "-1", "--decorate"])
        if rc_log == 0:
            postcheck_lines.append(f"== git log -1 --decorate ==\n{log_out}")
        rc_alembic, alembic_out, _ = run_cmd([py_exe, "-m", "alembic", "current"])
        if rc_alembic == 0:
            postcheck_lines.append(f"== alembic current ==\n{alembic_out}")

        log(
            f"Summary: events={len(events)} sources={len(sources)} max_inflight={RateLimitHandler.max_inflight} retry_attempts={retry_source.get('attempt_count')}"
        )
        log("=== PROOF COMPLETE ===")
        proof_passed = True
        return_code = 0

    except Exception as exc:  # noqa: BLE001
        log(f"FAIL: {exc}")
        log(traceback.format_exc())
        postcheck_lines = [f"run_id={run_id}", f"job_id={job_id}", "proof=FAIL", f"error={exc}"]
        return_code = 1

    finally:
        stop_fixture_server(fixture_server)
        try:
            if not proof_passed and return_code != 0:
                log("=== PROOF FAILED ===")
            write_artifacts(openapi_body, postcheck_lines, preflight_lines)
        except Exception as artifact_exc:  # noqa: BLE001
            log(f"artifact write failed: {artifact_exc}")

    return return_code


if __name__ == "__main__":
    sys.exit(main())

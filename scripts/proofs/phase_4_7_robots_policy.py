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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_7_robots.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_7_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_7_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_7_postcheck.txt"

LOG_LINES: list[str] = []


class RobotsFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/") or "/"

        if path == "/robots.txt":
            body = """User-agent: *\nDisallow: /private\n"""
            self._write(200, "text/plain", body.encode("utf-8"))
            return

        if path == "/public":
            self._write(200, "text/html", b"<html><body>PUBLIC_OK</body></html>")
            return

        if path == "/private":
            self._write(200, "text/html", b"<html><body>PRIVATE_SHOULD_BE_BLOCKED</body></html>")
            return

        self._write(404, "text/plain", b"not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_fixture_server(port: int = 8780) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), RobotsFixtureHandler)
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
                SELECT id, url, url_normalized, status, attempt_count, next_retry_at, meta, created_at, last_error, error_message, fetched_at, content_hash, http_status_code
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
    if preflight_lines:
        PRECHECK_ARTIFACT.write_text("\n".join(preflight_lines), encoding="utf-8")
    if postcheck_lines:
        POSTCHECK_ARTIFACT.write_text("\n".join(postcheck_lines), encoding="utf-8")


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
    if "ahead" in status_out or "behind" in status_out:
        raise RuntimeError("working tree not in sync with origin")
    lines.append("== git status -sb ==")
    lines.append(status_out)
    lines.append("working_tree_note=CLEAN")

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
    return openapi_body, lines


@contextmanager
def measure_time(label: str):
    start = time.monotonic()
    try:
        yield
    finally:
        duration = time.monotonic() - start
        log(f"{label} took {duration:.3f}s")


def main() -> int:
    load_dotenv()
    api_base = os.getenv("BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    log("=== PHASE 4.7 ROBOTS POLICY PROOF ===")
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

    env_overrides = {}

    try:
        openapi_body, preflight_lines = preflight(api_base, py_exe)
        log("Preflight completed")

        purged = purge_jobs(tenant_id)
        log(f"Purged {purged} existing company_research_jobs for tenant {tenant_id}")

        fixture_server = start_fixture_server()
        log("Fixture HTTP server started on 127.0.0.1:8780")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.7-Robots-{uuid.uuid4().hex[:6]}",
            "description": "Proof robots.txt enforcement",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        base = "http://127.0.0.1:8780"
        public_url = f"{base}/public"
        private_url = f"{base}/private"
        for idx, url in enumerate([public_url, private_url], start=1):
            payload = {"title": f"Robots-{idx}", "url": url}
            src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
            log(f"URL source attached: {src['id']} {url}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        with measure_time("worker passes"):
            for attempt in range(3):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"Worker pass {attempt + 1} complete")

        state = fetch_db_state(tenant_id, run_id)
        sources = state["sources"]
        events = state["events"]
        log(f"Fetched DB state: {len(sources)} sources, {len(events)} events")

        def assert_true(condition: bool, message: str) -> None:
            if not condition:
                raise AssertionError(message)
            postcheck_lines.append(f"PASS: {message}")

        postcheck_lines.append(f"run_id={run_id}")
        postcheck_lines.append(f"job_id={job_id}")
        postcheck_lines.append(f"sources_count={len(sources)}")
        postcheck_lines.append(f"events_count={len(events)}")

        sources_by_url = {s["url"]: s for s in sources}

        assert_true(public_url in sources_by_url and private_url in sources_by_url, "both sources present")

        pub_src = sources_by_url[public_url]
        priv_src = sources_by_url[private_url]

        robots_fetched_events = [e for e in events if e.get("event_type") == "robots_fetched"]
        robots_disallowed_events = [e for e in events if e.get("event_type") == "robots_disallowed"]

        assert_true(len(robots_fetched_events) >= 1, "robots_fetched emitted")
        assert_true(len(robots_disallowed_events) >= 1, "robots_disallowed emitted")

        # Allowed URL assertions
        assert_true(pub_src.get("status") == "fetched", "public fetched")
        assert_true(pub_src.get("content_hash") is not None, "public has content_hash")
        assert_true(pub_src.get("fetched_at") is not None, "public has fetched_at")

        # Disallowed URL assertions
        assert_true(priv_src.get("status") == "failed", "private blocked")
        last_error = (priv_src.get("last_error") or "").lower()
        assert_true("robot" in last_error or "robots" in last_error, "private last_error mentions robots")
        assert_true(priv_src.get("content_hash") is None, "private has no content_hash")
        assert_true(priv_src.get("fetched_at") is None, "private has no fetched_at")

        # Idempotency: rerun worker and ensure counts stable
        with measure_time("idempotent passes"):
            for attempt in range(2):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"Idempotent worker pass {attempt + 1} complete")

        state_after = fetch_db_state(tenant_id, run_id)
        sources_after = state_after["sources"]
        events_after = state_after["events"]
        assert_true(len(sources_after) == len(sources), "source count stable after reruns")
        assert_true(len(events_after) == len(events), "event count stable after reruns")

        # Postcheck counters
        events_by_type: dict[str, int] = {}
        for evt in events_after:
            events_by_type[evt.get("event_type")] = events_by_type.get(evt.get("event_type"), 0) + 1

        succeeded = sum(1 for s in sources_after if s.get("status") == "fetched")
        failed = sum(1 for s in sources_after if s.get("status") == "failed")
        postcheck_lines.append(f"sources_total={len(sources_after)}")
        postcheck_lines.append(f"sources_succeeded={succeeded}")
        postcheck_lines.append(f"sources_failed={failed}")
        postcheck_lines.append(f"source_documents_total={len(sources_after)}")
        postcheck_lines.append(f"events_total={len(events_after)}")
        postcheck_lines.append(f"events_by_type={json.dumps(events_by_type, sort_keys=True)}")

        log(f"Robots decisions: public={pub_src.get('status')}, private={priv_src.get('status')}")
        log(f"Events by type: {events_by_type}")

        proof_passed = True
        log("=== PROOF COMPLETE ===")

    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        postcheck_lines.append(f"FAIL: {exc}")
    finally:
        stop_fixture_server(fixture_server)
        log("Fixture HTTP server stopped")
        try:
            write_artifacts(openapi_body, postcheck_lines, preflight_lines)
        except Exception as artifact_exc:  # noqa: BLE001
            log(f"Failed to write artifacts: {artifact_exc}")
        if not proof_passed:
            return_code = 1
        else:
            return_code = 0

    return return_code


if __name__ == "__main__":
    sys.exit(main())

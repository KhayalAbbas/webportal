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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_5_redirect_handling.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_5_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_5_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_5_postcheck.txt"

LOG_LINES: list[str] = []
MAX_REDIRECTS_UNDER_TEST = 3


class RedirectFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path == "":
            path = "/"

        if path.endswith("/redirect/chain/start"):
            self._redirect(302, "/redirect/chain/hop1")
            return
        if path.endswith("/redirect/chain/hop1"):
            self._redirect(307, "/redirect/chain/hop2")
            return
        if path.endswith("/redirect/chain/hop2"):
            self._redirect(308, "/redirect/chain/final")
            return
        if path.endswith("/redirect/chain/final"):
            self._write_plain(200, "CHAIN_FINAL")
            return

        if path.endswith("/redirect/loop/a"):
            self._redirect(302, "/redirect/loop/b")
            return
        if path.endswith("/redirect/loop/b"):
            self._redirect(301, "/redirect/loop/a")
            return

        if path.endswith("/redirect/deep/0"):
            self._redirect(302, "/redirect/deep/1")
            return
        if path.endswith("/redirect/deep/1"):
            self._redirect(302, "/redirect/deep/2")
            return
        if path.endswith("/redirect/deep/2"):
            self._redirect(302, "/redirect/deep/3")
            return
        if path.endswith("/redirect/deep/3"):
            self._redirect(302, "/redirect/deep/4")
            return
        if path.endswith("/redirect/deep/4"):
            self._write_plain(200, "DEEP_FINAL")
            return

        if path.endswith("/redirect/missing_location"):
            # Intentionally omit Location header to trigger missing-location handling
            self.send_response(302)
            self.end_headers()
            return

        self._write_plain(404, "not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _redirect(self, status: int, location: str) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.end_headers()

    def _write_plain(self, status: int, body: str) -> None:
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def start_fixture_server(port: int = 8777) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), RedirectFixtureHandler)
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
                SELECT id, url, url_normalized, status, attempt_count, next_retry_at, meta, created_at, last_error, error_message, fetched_at, content_hash, http_status_code, http_final_url, canonical_final_url
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

    log("=== PHASE 4.5 REDIRECT HANDLING PROOF ===")
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
        "MAX_REDIRECTS": str(MAX_REDIRECTS_UNDER_TEST),
    }

    try:
        openapi_body, preflight_lines = preflight(api_base, py_exe)
        log("Preflight completed")

        purged = purge_jobs(tenant_id)
        log(f"Purged {purged} existing company_research_jobs for tenant {tenant_id}")

        fixture_server = start_fixture_server()
        log("Fixture HTTP server started on 127.0.0.1:8777")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.5-Redirects-{uuid.uuid4().hex[:6]}",
            "description": "Proof redirect handling",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        base = "http://127.0.0.1:8777"
        redirect_ok = f"{base}/redirect/chain/start"
        redirect_loop = f"{base}/redirect/loop/a"
        redirect_limit = f"{base}/redirect/deep/0"
        redirect_missing = f"{base}/redirect/missing_location"
        for idx, url in enumerate([redirect_ok, redirect_loop, redirect_limit, redirect_missing], start=1):
            payload = {"title": f"Redirect-{idx}", "url": url}
            src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
            log(f"URL source attached: {src['id']} {url}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        with measure_time("worker passes"):
            for attempt in range(4):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"Worker pass {attempt + 1} complete")

        state = fetch_db_state(tenant_id, run_id)
        sources = state["sources"]
        events = state["events"]
        log(f"Fetched DB state: {len(sources)} sources, {len(events)} events")

        postcheck_lines.append(f"run_id={run_id}")
        postcheck_lines.append(f"job_id={job_id}")
        postcheck_lines.append(f"sources_count={len(sources)}")
        postcheck_lines.append(f"events_count={len(events)}")

        sources_by_url = {s["url"]: s for s in sources}

        def assert_true(condition: bool, message: str) -> None:
            if not condition:
                raise AssertionError(message)
            postcheck_lines.append(f"PASS: {message}")

        assert_true(
            redirect_ok in sources_by_url
            and redirect_loop in sources_by_url
            and redirect_limit in sources_by_url
            and redirect_missing in sources_by_url,
            "all sources present",
        )

        ok_src = sources_by_url[redirect_ok]
        loop_src = sources_by_url[redirect_loop]
        limit_src = sources_by_url[redirect_limit]
        missing_src = sources_by_url[redirect_missing]

        ok_fetch_info = (ok_src.get("meta") or {}).get("fetch_info", {})
        loop_fetch_info = (loop_src.get("meta") or {}).get("fetch_info", {})
        limit_fetch_info = (limit_src.get("meta") or {}).get("fetch_info", {})
        missing_fetch_info = (missing_src.get("meta") or {}).get("fetch_info", {})

        ok_chain = ok_fetch_info.get("redirect_chain") or []
        loop_chain = ((loop_fetch_info.get("http") or {}).get("redirect_chain")) or []
        limit_chain = ((limit_fetch_info.get("http") or {}).get("redirect_chain")) or []
        missing_chain = ((missing_fetch_info.get("http") or {}).get("redirect_chain")) or []

        assert_true(ok_src.get("status") == "fetched", "redirect chain source fetched")
        assert_true(ok_src.get("http_status_code") == 200, "redirect chain HTTP 200 final")
        assert_true(ok_src.get("canonical_final_url", "").endswith("/redirect/chain/final"), "canonical_final_url preserved for redirect chain")
        assert_true(len(ok_chain) == 3, "redirect chain follows all hops")
        assert_true(ok_src.get("last_error") is None, "redirect chain has no last_error")

        assert_true(loop_src.get("status") == "failed", "loop source failed")
        assert_true(loop_src.get("last_error") == "redirect_loop_detected", "loop source marked as redirect loop")
        assert_true(len(loop_chain) >= 2, "loop source captured redirect chain")

        assert_true(limit_src.get("status") == "failed", "redirect limit source failed")
        assert_true(limit_src.get("last_error") == "redirect_limit_exceeded", "redirect limit source marked correctly")
        assert_true(len(limit_chain) > MAX_REDIRECTS_UNDER_TEST, "redirect limit captured chain beyond limit")

        assert_true(missing_src.get("status") == "failed", "missing-location source failed")
        assert_true(missing_src.get("last_error") == "redirect_missing_location", "missing-location source marked correctly")
        assert_true(missing_chain is not None, "missing-location redirect chain captured")

        def find_events(evt_type: str, source_id: str) -> list[dict]:
            return [e for e in events if e.get("event_type") == evt_type and (e.get("input_json") or {}).get("source_id") == source_id]

        ok_events = find_events("redirect_followed", str(ok_src.get("id")))
        loop_events = find_events("redirect_loop_detected", str(loop_src.get("id")))
        limit_events = find_events("redirect_limit_reached", str(limit_src.get("id")))
        missing_events = find_events("redirect_missing_location", str(missing_src.get("id")))

        assert_true(len(ok_events) == 3, "redirect_followed emitted for each hop")
        assert_true(len(loop_events) == 1, "redirect_loop_detected event emitted")
        assert_true(len(limit_events) == 1, "redirect_limit_reached event emitted")
        assert_true(len(missing_events) == 1, "redirect_missing_location event emitted")

        resolved_events = find_events("redirect_resolved", str(ok_src.get("id")))
        assert_true(len(resolved_events) >= 1, "redirect_resolved emitted for successful chain")

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

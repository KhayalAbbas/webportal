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
from typing import Any
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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_8_caching.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_8_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_8_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_8_postcheck.txt"

FIXED_LM = "Tue, 01 Jul 2025 12:00:00 GMT"
LOG_LINES: list[str] = []


class ConditionalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path
        if path.startswith("/etag"):
            inm = self.headers.get("If-None-Match")
            if inm and inm.strip() == '"v1"':
                self._write(304, {"ETag": '"v1"'})
                return
            self._write(200, {"ETag": '"v1"'}, body=b"V1")
            return

        if path.startswith("/lm"):
            ims = self.headers.get("If-Modified-Since")
            if ims:
                try:
                    ims_dt = datetime.strptime(ims, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
                    fixed_dt = datetime.strptime(FIXED_LM, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
                    if ims_dt >= fixed_dt:
                        self._write(304, {"Last-Modified": FIXED_LM})
                        return
                except Exception:
                    pass
            self._write(200, {"Last-Modified": FIXED_LM}, body=b"LMV1")
            return

        self._write(404, {}, body=b"not found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write(self, status: int, headers: dict[str, str], body: bytes | None = None) -> None:
        payload = body or b""
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)


def start_fixture_server(port: int = 8782) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), ConditionalHandler)
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
    if "\n" in status_out.strip() or status_out.strip() not in {"## master...origin/master", "## master"}:
        raise RuntimeError(f"working tree not clean: {status_out}")
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


def count_events(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for evt in events:
        counts[evt.get("event_type")] = counts.get(evt.get("event_type"), 0) + 1
    return counts


def main() -> int:
    load_dotenv()
    api_base = os.getenv("BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    log("=== PHASE 4.8 CONDITIONAL FETCH PROOF ===")
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
        log("Fixture HTTP server started on 127.0.0.1:8782")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.8-Conditional-{uuid.uuid4().hex[:6]}",
            "description": "Proof conditional fetch caching",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        base = "http://127.0.0.1:8782"
        etag_url = f"{base}/etag"
        lm_url = f"{base}/lm"
        for idx, url in enumerate([etag_url, lm_url], start=1):
            payload = {"title": f"Conditional-{idx}", "url": url}
            src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
            log(f"URL source attached: {src['id']} {url}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        with measure_time("worker passes P1"):
            for attempt in range(3):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"P1 worker pass {attempt + 1} complete")

        state_p1 = fetch_db_state(tenant_id, run_id)
        sources_p1 = state_p1["sources"]
        events_p1 = state_p1["events"]
        events_by_type_p1 = count_events(events_p1)
        log(f"P1 DB: {len(sources_p1)} sources, {len(events_p1)} events")

        def assert_true(condition: bool, message: str) -> None:
            if not condition:
                raise AssertionError(message)
            postcheck_lines.append(f"PASS: {message}")

        postcheck_lines.append(f"run_id={run_id}")
        postcheck_lines.append(f"job_id={job_id}")

        sources_by_url_p1 = {s["url"]: s for s in sources_p1}
        assert_true(etag_url in sources_by_url_p1 and lm_url in sources_by_url_p1, "both sources present")

        etag_src_p1 = sources_by_url_p1[etag_url]
        lm_src_p1 = sources_by_url_p1[lm_url]

        def _validators(meta: dict | None) -> dict:
            if not meta or not isinstance(meta, dict):
                return {}
            return meta.get("validators") or {}

        etag_val_p1 = _validators(etag_src_p1.get("meta"))
        lm_val_p1 = _validators(lm_src_p1.get("meta"))

        assert_true(etag_src_p1.get("status") == "fetched", "etag source fetched on P1")
        assert_true(lm_src_p1.get("status") == "fetched", "last-modified source fetched on P1")
        assert_true(etag_src_p1.get("content_hash") is not None, "etag content_hash set P1")
        assert_true(lm_src_p1.get("content_hash") is not None, "last-modified content_hash set P1")
        assert_true(etag_val_p1.get("etag") == '"v1"', "etag validator stored")
        assert_true(lm_val_p1.get("last_modified") == FIXED_LM, "last-modified validator stored")
        assert_true(etag_val_p1.get("pending_recheck") is True, "etag pending_recheck set")
        assert_true(lm_val_p1.get("pending_recheck") is True, "lm pending_recheck set")

        postcheck_lines.append(f"events_p1_total={len(events_p1)}")
        postcheck_lines.append(f"events_p1_by_type={json.dumps(events_by_type_p1, sort_keys=True)}")
        postcheck_lines.append(f"sources_p1_total={len(sources_p1)}")
        postcheck_lines.append(f"source_documents_total_p1={len(sources_p1)}")

        with measure_time("worker passes P2"):
            for attempt in range(2):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"P2 worker pass {attempt + 1} complete")

        state_p2 = fetch_db_state(tenant_id, run_id)
        sources_p2 = state_p2["sources"]
        events_p2 = state_p2["events"]
        events_by_type_p2 = count_events(events_p2)
        log(f"P2 DB: {len(sources_p2)} sources, {len(events_p2)} events")

        sources_by_url_p2 = {s["url"]: s for s in sources_p2}
        etag_src_p2 = sources_by_url_p2[etag_url]
        lm_src_p2 = sources_by_url_p2[lm_url]
        etag_val_p2 = _validators(etag_src_p2.get("meta"))
        lm_val_p2 = _validators(lm_src_p2.get("meta"))

        assert_true(len(sources_p2) == len(sources_p1), "no new source_documents after P2")
        assert_true(etag_src_p2.get("content_hash") == etag_src_p1.get("content_hash"), "etag content_hash unchanged P2")
        assert_true(lm_src_p2.get("content_hash") == lm_src_p1.get("content_hash"), "lm content_hash unchanged P2")
        assert_true(etag_val_p2.get("pending_recheck") is False, "etag pending_recheck cleared P2")
        assert_true(lm_val_p2.get("pending_recheck") is False, "lm pending_recheck cleared P2")
        assert_true(events_by_type_p2.get("not_modified", 0) >= 2, "not_modified events emitted P2")

        postcheck_lines.append(f"events_p2_total={len(events_p2)}")
        postcheck_lines.append(f"events_p2_by_type={json.dumps(events_by_type_p2, sort_keys=True)}")
        postcheck_lines.append(f"source_documents_total_p2={len(sources_p2)}")

        with measure_time("worker passes P3"):
            for attempt in range(2):
                run_worker_once(py_exe, env_overrides)
                time.sleep(0.4)
                log(f"P3 worker pass {attempt + 1} complete")

        state_p3 = fetch_db_state(tenant_id, run_id)
        sources_p3 = state_p3["sources"]
        events_p3 = state_p3["events"]
        events_by_type_p3 = count_events(events_p3)
        log(f"P3 DB: {len(sources_p3)} sources, {len(events_p3)} events")

        assert_true(len(sources_p3) == len(sources_p2), "source count stable on P3")
        assert_true(len(events_p3) == len(events_p2), "event count stable on P3")

        sources_by_url_p3 = {s["url"]: s for s in sources_p3}
        assert_true(sources_by_url_p3[etag_url].get("content_hash") == etag_src_p2.get("content_hash"), "etag hash stable P3")
        assert_true(sources_by_url_p3[lm_url].get("content_hash") == lm_src_p2.get("content_hash"), "lm hash stable P3")

        # Postcheck counters
        succeeded = sum(1 for s in sources_p3 if s.get("status") == "fetched")
        failed = sum(1 for s in sources_p3 if s.get("status") == "failed")
        postcheck_lines.append(f"sources_total={len(sources_p3)}")
        postcheck_lines.append(f"sources_succeeded={succeeded}")
        postcheck_lines.append(f"sources_failed={failed}")
        postcheck_lines.append(f"events_total={len(events_p3)}")
        postcheck_lines.append(f"events_by_type={json.dumps(events_by_type_p3, sort_keys=True)}")
        postcheck_lines.append(f"validators_etag={json.dumps(etag_val_p2, sort_keys=True)}")
        postcheck_lines.append(f"validators_lm={json.dumps(lm_val_p2, sort_keys=True)}")

        log(f"Validators P2: etag={etag_val_p2} lm={lm_val_p2}")
        log(f"Events by type P2: {events_by_type_p2}")

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
        return_code = 0 if proof_passed else 1

    return return_code


if __name__ == "__main__":
    sys.exit(main())

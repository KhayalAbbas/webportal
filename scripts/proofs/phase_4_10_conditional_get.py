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
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_10_conditional_get.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_10_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_10_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_10_postcheck.txt"

FIXED_LAST_MODIFIED = "Wed, 01 Jan 2025 00:00:00 GMT"

LOG_LINES: list[str] = []
STATE = {
    "etag_version": "v1",
    "requests": {
        "etag_resource": [],
        "last_modified_resource": [],
        "no_store_resource": [],
    },
}


def reset_state() -> None:
    STATE["etag_version"] = "v1"
    for key in STATE["requests"]:
        STATE["requests"][key] = []


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


@contextmanager
def start_fixture_server(port: int):
    handler = make_handler()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        log(f"Fixture server started on 127.0.0.1:{port}")
        yield server
    finally:
        server.shutdown()
        log("Fixture server stopped")


def make_handler() -> Callable[..., BaseHTTPRequestHandler]:
    class FixtureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            headers_in = {k.lower(): v for k, v in self.headers.items()}
            log(f"REQ path={path} hdrs={json.dumps(headers_in, sort_keys=True)}")

            if path == "/etag_resource":
                STATE["requests"]["etag_resource"].append(headers_in)
                etag_header = f'"{STATE["etag_version"]}"'
                if headers_in.get("if-none-match") == etag_header:
                    self._write(304, {"ETag": etag_header}, b"")
                    return
                body = STATE["etag_version"].encode("utf-8")
                self._write(200, {"ETag": etag_header, "Content-Type": "text/plain"}, body)
                return

            if path == "/last_modified_resource":
                STATE["requests"]["last_modified_resource"].append(headers_in)
                lm_dt = parsedate_to_datetime(FIXED_LAST_MODIFIED)
                if_since = headers_in.get("if-modified-since")
                if if_since:
                    try:
                        since_dt = parsedate_to_datetime(if_since)
                        if since_dt and since_dt >= lm_dt:
                            self._write(304, {"Last-Modified": FIXED_LAST_MODIFIED}, b"")
                            return
                    except Exception:
                        pass
                self._write(200, {"Last-Modified": FIXED_LAST_MODIFIED, "Content-Type": "text/plain"}, b"lm1")
                return

            if path == "/no_store_resource":
                STATE["requests"]["no_store_resource"].append(headers_in)
                headers = {"ETag": '"ns1"', "Cache-Control": "no-store", "Content-Type": "text/plain"}
                self._write(200, headers, b"ns1")
                return

            self._write(404, {}, b"not found")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _write(self, status: int, headers: dict[str, str], body: bytes) -> None:
            payload = body or b""
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload:
                self.wfile.write(payload)

    return FixtureHandler


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


def _get_dsn() -> str:
    raw = os.environ.get("ATS_DSN", settings.DATABASE_URL)
    if "+asyncpg" in raw:
        return raw.replace("+asyncpg", "")
    return raw


def db_ping() -> str:
    dsn = _get_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1")
            row = cur.fetchone()
            if not row or row[0] != 1:
                raise RuntimeError("DB ping failed")
    return "DB_OK"


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


def count_events(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = event.get("event_type") or "unknown"
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


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


def compare_openapi_identity(openapi_body: dict) -> str:
    ref_path = Path("openapi.json")
    if not ref_path.exists():
        raise RuntimeError("openapi.json missing locally")
    live_bytes = json.dumps(openapi_body, sort_keys=True).encode("utf-8")
    ref_bytes = ref_path.read_bytes()
    try:
        ref_json_sorted = json.dumps(json.loads(ref_bytes.decode("utf-8")), sort_keys=True).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"unable to parse local openapi.json: {exc}")
    if live_bytes != ref_json_sorted:
        raise RuntimeError("live openapi.json does not match local openapi.json")
    return "openapi matches local openapi.json"


def preflight(api_base: str, py_exe: str) -> tuple[dict, list[str]]:
    lines: list[str] = []

    resp = requests.get(urljoin(api_base, "/openapi.json"), timeout=5)
    if resp.status_code != 200:
        raise RuntimeError(f"openapi check failed: status {resp.status_code}")
    openapi_body = resp.json()
    lines.append("== openapi.json ==")
    lines.append(f"status={resp.status_code} bytes={len(resp.text)}")
    lines.append(compare_openapi_identity(openapi_body))

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
    lines.append(f"git_status={status_out.strip()}")

    rc_log, log_out, _ = run_cmd([git_exe, "log", "-1", "--decorate"])
    if rc_log != 0:
        raise RuntimeError("git log failed")
    lines.append(f"git_log={log_out.strip()}")

    rc_alembic, alembic_current, _ = run_cmd([py_exe, "-m", "alembic", "current"])
    if rc_alembic != 0:
        raise RuntimeError("alembic current failed")
    rc_heads, alembic_heads, _ = run_cmd([py_exe, "-m", "alembic", "heads"])
    if rc_heads != 0:
        raise RuntimeError("alembic heads failed")
    if alembic_current.strip() != alembic_heads.strip():
        raise RuntimeError("alembic current not at head")
    lines.append(f"alembic_current={alembic_current.strip()}")
    lines.append(f"alembic_heads={alembic_heads.strip()}")

    return openapi_body, lines


def write_artifacts(openapi_body: dict | None, postcheck_lines: list[str], preflight_lines: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
    if openapi_body is not None:
        OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
    if preflight_lines:
        PRECHECK_ARTIFACT.write_text("\n".join(preflight_lines), encoding="utf-8")
    if postcheck_lines:
        POSTCHECK_ARTIFACT.write_text("\n".join(postcheck_lines), encoding="utf-8")


def _validators(meta: dict | None) -> dict:
    if not meta:
        return {}
    return meta.get("validators") or {}


def sources_by_url(sources: list[dict]) -> dict[str, dict]:
    return {s.get("url"): s for s in sources}


def main() -> int:
    load_dotenv()
    api_base = os.getenv("API_BASE", API_DEFAULT)
    tenant_id = os.getenv("ATS_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("ATS_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("ATS_PASSWORD", PASSWORD_DEFAULT)
    py_exe = sys.executable

    postcheck_lines: list[str] = []
    preflight_lines: list[str] = []
    proof_passed = False
    run_id = None
    job_id = None
    openapi_body: dict | None = None

    try:
        openapi_body, preflight_lines = preflight(api_base, py_exe)
        log("Preflight completed")

        purged = purge_jobs(tenant_id)
        log(f"Purged {purged} existing company_research_jobs for tenant {tenant_id}")

        reset_state()
        port = 8787
        with start_fixture_server(port):
            token = login(api_base, tenant_id, email, password)
            headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

            role_id = select_role(api_base, headers)
            run_payload = {
                "role_mandate_id": role_id,
                "name": f"Phase4.10-Conditional-{uuid.uuid4().hex[:6]}",
                "description": "Proof conditional GET",
                "sector": "banking",
                "region_scope": ["US"],
            }
            run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
            run_id = run["id"]
            log(f"Run created: {run_id}")

            base = f"http://127.0.0.1:{port}"
            etag_url = f"{base}/etag_resource"
            lm_url = f"{base}/last_modified_resource"
            no_store_url = f"{base}/no_store_resource"
            urls = [etag_url, lm_url, no_store_url]

            for idx, url in enumerate(urls, start=1):
                payload = {"title": f"P4.10-{idx}", "url": url}
                src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
                log(f"URL source attached: {src['id']} {url}")

            start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
            job_id = start_resp.get("id") or start_resp.get("job_id")
            log(f"Run started (job {job_id})")

            env_overrides: dict[str, str] = {}

            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            log("P1 worker pass complete")

            state_p1 = fetch_db_state(tenant_id, run_id)
            sources_p1 = state_p1["sources"]
            events_p1 = state_p1["events"]
            events_by_type_p1 = count_events(events_p1)
            log(f"P1 DB: {len(sources_p1)} sources, {len(events_p1)} events")

            src_by_url_p1 = sources_by_url(sources_p1)
            etag_src_p1 = src_by_url_p1[etag_url]
            lm_src_p1 = src_by_url_p1[lm_url]
            ns_src_p1 = src_by_url_p1[no_store_url]
            etag_val_p1 = _validators(etag_src_p1.get("meta"))
            lm_val_p1 = _validators(lm_src_p1.get("meta"))
            ns_val_p1 = _validators(ns_src_p1.get("meta"))

            def assert_true(condition: bool, message: str) -> None:
                if not condition:
                    raise AssertionError(message)
                postcheck_lines.append(f"PASS: {message}")

            assert_true(len(sources_p1) == len(urls), "all sources present P1")
            assert_true(all(s.get("status") == "fetched" for s in sources_p1), "all sources fetched P1")
            assert_true(len(STATE["requests"]["etag_resource"]) == 1, "etag fetched once P1")
            assert_true(len(STATE["requests"]["last_modified_resource"]) == 1, "last-modified fetched once P1")
            assert_true(len(STATE["requests"]["no_store_resource"]) == 1, "no-store fetched once P1")
            assert_true(etag_val_p1.get("etag") == '"v1"', "etag stored P1")
            assert_true(lm_val_p1.get("last_modified") == FIXED_LAST_MODIFIED, "last-modified stored P1")
            assert_true(not ns_val_p1.get("etag") and not ns_val_p1.get("last_modified"), "no-store validators not persisted")

            postcheck_lines.append(f"events_p1_total={len(events_p1)}")
            postcheck_lines.append(f"events_p1_by_type={json.dumps(events_by_type_p1, sort_keys=True)}")
            postcheck_lines.append(f"sources_p1_total={len(sources_p1)}")

            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            log("P2 worker pass complete")

            state_p2 = fetch_db_state(tenant_id, run_id)
            sources_p2 = state_p2["sources"]
            events_p2 = state_p2["events"]
            events_by_type_p2 = count_events(events_p2)
            log(f"P2 DB: {len(sources_p2)} sources, {len(events_p2)} events")

            src_by_url_p2 = sources_by_url(sources_p2)
            etag_src_p2 = src_by_url_p2[etag_url]
            lm_src_p2 = src_by_url_p2[lm_url]
            ns_src_p2 = src_by_url_p2[no_store_url]
            etag_val_p2 = _validators(etag_src_p2.get("meta"))
            lm_val_p2 = _validators(lm_src_p2.get("meta"))
            ns_val_p2 = _validators(ns_src_p2.get("meta"))

            not_mod_count_p2 = events_by_type_p2.get("page_not_modified", 0) + events_by_type_p2.get("not_modified", 0)
            assert_true(len(STATE["requests"]["etag_resource"]) == 2, "etag revalidated once P2")
            assert_true(len(STATE["requests"]["last_modified_resource"]) == 2, "last-modified revalidated once P2")
            assert_true(len(STATE["requests"]["no_store_resource"]) == 2, "no-store refetched P2")
            assert_true(STATE["requests"]["etag_resource"][1].get("if-none-match") == '"v1"', "etag conditional header sent P2")
            assert_true(STATE["requests"]["last_modified_resource"][1].get("if-modified-since") == FIXED_LAST_MODIFIED, "last-modified conditional header sent P2")
            assert_true(STATE["requests"]["no_store_resource"][1].get("if-none-match") is None, "no-store did not send conditional header P2")
            assert_true(len(sources_p2) == len(sources_p1), "no new source_documents P2")
            assert_true(etag_src_p2.get("content_hash") == etag_src_p1.get("content_hash"), "etag hash unchanged P2")
            assert_true(lm_src_p2.get("content_hash") == lm_src_p1.get("content_hash"), "last-modified hash unchanged P2")
            assert_true(not_mod_count_p2 >= 2, "not_modified events recorded P2")
            assert_true(not ns_val_p2.get("etag") and not ns_val_p2.get("last_modified"), "no-store validators still absent P2")

            postcheck_lines.append(f"events_p2_total={len(events_p2)}")
            postcheck_lines.append(f"events_p2_by_type={json.dumps(events_by_type_p2, sort_keys=True)}")
            postcheck_lines.append(f"sources_p2_total={len(sources_p2)}")

            STATE["etag_version"] = "v2"
            log("Switched etag resource to v2")
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            log("P3 worker pass 1 complete")

            state_p3 = fetch_db_state(tenant_id, run_id)
            sources_p3 = state_p3["sources"]
            events_p3 = state_p3["events"]
            events_by_type_p3 = count_events(events_p3)
            log(f"P3 DB: {len(sources_p3)} sources, {len(events_p3)} events")

            src_by_url_p3 = sources_by_url(sources_p3)
            etag_src_p3 = src_by_url_p3[etag_url]
            lm_src_p3 = src_by_url_p3[lm_url]
            ns_src_p3 = src_by_url_p3[no_store_url]

            assert_true(len(STATE["requests"]["etag_resource"]) == 3, "etag refetched after version bump")
            assert_true(etag_src_p3.get("content_hash") != etag_src_p2.get("content_hash"), "etag hash updated P3")
            assert_true(lm_src_p3.get("content_hash") == lm_src_p2.get("content_hash"), "last-modified hash stable P3")
            assert_true(ns_src_p3.get("content_hash") is not None, "no-store still fetched P3")
            assert_true(len(sources_p3) == len(sources_p2), "source_documents remain stable P3")

            postcheck_lines.append(f"events_p3_total={len(events_p3)}")
            postcheck_lines.append(f"events_p3_by_type={json.dumps(events_by_type_p3, sort_keys=True)}")
            postcheck_lines.append(f"sources_p3_total={len(sources_p3)}")

            run_worker_once(py_exe, env_overrides)
            time.sleep(0.4)
            log("P4 idempotency worker pass complete")

            state_p4 = fetch_db_state(tenant_id, run_id)
            sources_p4 = state_p4["sources"]
            events_p4 = state_p4["events"]
            events_by_type_p4 = count_events(events_p4)
            log(f"P4 DB: {len(sources_p4)} sources, {len(events_p4)} events")

            src_by_url_p4 = sources_by_url(sources_p4)
            assert_true(len(sources_p4) == len(sources_p3), "source_documents stable P4")
            assert_true(src_by_url_p4[etag_url].get("content_hash") == etag_src_p3.get("content_hash"), "etag hash stable P4")
            assert_true(src_by_url_p4[lm_url].get("content_hash") == lm_src_p3.get("content_hash"), "last-modified hash stable P4")
            assert_true(src_by_url_p4[no_store_url].get("content_hash") == ns_src_p3.get("content_hash"), "no-store hash stable P4")

            postcheck_lines.append(f"sources_total={len(sources_p4)}")
            succeeded = len([s for s in sources_p4 if s.get("status") not in {"failed", "fetch_failed"}])
            failed = len([s for s in sources_p4 if s.get("status") in {"failed", "fetch_failed"}])
            postcheck_lines.append(f"sources_succeeded={succeeded}")
            postcheck_lines.append(f"sources_failed={failed}")
            postcheck_lines.append(f"events_total={len(events_p4)}")
            postcheck_lines.append(f"events_by_type={json.dumps(events_by_type_p4, sort_keys=True)}")
            postcheck_lines.append(f"etag_requests={len(STATE['requests']['etag_resource'])}")
            postcheck_lines.append(f"last_modified_requests={len(STATE['requests']['last_modified_resource'])}")
            postcheck_lines.append(f"no_store_requests={len(STATE['requests']['no_store_resource'])}")
            postcheck_lines.append(f"etag_hash={etag_src_p3.get('content_hash')}")
            postcheck_lines.append(f"lm_hash={lm_src_p3.get('content_hash')}")
            postcheck_lines.append(f"ns_hash={ns_src_p3.get('content_hash')}")

            git_exe = shutil.which("git") or r"C:\\Program Files\\Git\\cmd\\git.exe"
            rc_status, status_out, _ = run_cmd([git_exe, "status", "-sb"])
            rc_log, log_out, _ = run_cmd([git_exe, "log", "-1", "--decorate"])
            rc_alembic, alembic_current, _ = run_cmd([py_exe, "-m", "alembic", "current"])
            rc_heads, alembic_heads, _ = run_cmd([py_exe, "-m", "alembic", "heads"])
            postcheck_lines.append(f"git_status={status_out.strip()}")
            postcheck_lines.append(f"git_log={log_out.strip()}")
            postcheck_lines.append(f"alembic_current={alembic_current.strip()}")
            postcheck_lines.append(f"alembic_heads={alembic_heads.strip()}")

            postcheck_lines.append(f"run_id={run_id}")
            postcheck_lines.append(f"job_id={job_id}")
            postcheck_lines.append("RESULT=PASS")
            proof_passed = True

    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        postcheck_lines.append(f"FAIL: {exc}")
        postcheck_lines.append("RESULT=FAIL")
        return_code = 1
    else:
        return_code = 0 if proof_passed else 1
    finally:
        log("=== PROOF COMPLETE ===")
        write_artifacts(openapi_body, postcheck_lines, preflight_lines)

    return return_code


if __name__ == "__main__":
    sys.exit(main())

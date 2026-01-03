import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin

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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_4_rate_limit_and_retry_after.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_4_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_4_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_4_postcheck.txt"

LOG_LINES: list[str] = []


class RateLimitHandler(BaseHTTPRequestHandler):
    retry_after_first = True

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path.endswith("/ok_fast"):
            self._write_plain(200, "OK_FAST")
            return

        if path.endswith("/retry_after"):
            if RateLimitHandler.retry_after_first:
                RateLimitHandler.retry_after_first = False
                self.send_response(429)
                self.send_header("Retry-After", "2")
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


def start_fixture_server(port: int = 8766) -> ThreadingHTTPServer:
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


def wait_for_api(api_base: str) -> requests.Response:
    for _ in range(20):
        try:
            resp = requests.get(urljoin(api_base, "/openapi.json"), timeout=2)
            resp.raise_for_status()
            return resp
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError("API did not become ready after 20s")


async def fetch_db_state(tenant_id: str, run_id: str) -> dict:
    async with async_session_maker() as session:
        src_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, url, url_normalized, status, attempt_count, next_retry_at, meta, created_at
                    FROM source_documents
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                    ORDER BY created_at ASC
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
                    ORDER BY created_at ASC
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).mappings().all()

    return {
        "sources": [dict(r) for r in src_rows],
        "events": [dict(e) for e in events],
    }


def write_artifacts(openapi_body: dict | None, postcheck_lines: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
    if openapi_body is not None:
        OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
        log(f"OpenAPI snapshot saved to {OPENAPI_ARTIFACT}")
    if postcheck_lines:
        POSTCHECK_ARTIFACT.write_text("\n".join(postcheck_lines), encoding="utf-8")
        log(f"Postcheck saved to {POSTCHECK_ARTIFACT}")


def main() -> int:
    load_dotenv()
    api_base = os.getenv("BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    log("=== PHASE 4.4 RATE LIMIT + RETRY-AFTER PROOF ===")
    log(f"API Base: {api_base}")
    log(f"Tenant: {tenant_id}")

    fixture_server: ThreadingHTTPServer | None = None
    return_code = 1
    openapi_body: dict | None = None
    postcheck_lines: list[str] = []

    env_overrides = {
        "PER_DOMAIN_CONCURRENCY": "1",
        "PER_DOMAIN_MIN_DELAY_MS": "200",
        "GLOBAL_CONCURRENCY": "8",
    }

    try:
        openapi_resp = wait_for_api(api_base)
        openapi_body = openapi_resp.json()
        log(f"OpenAPI status={openapi_resp.status_code} length={len(openapi_resp.text)}")

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

        for attempt in range(10):
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.5)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s for s in steps}
            fetch_state = statuses.get("fetch_url_sources", {})
            process_state = statuses.get("process_sources", {})
            finalize_state = statuses.get("finalize", {})
            log(
                f"Worker pass {attempt+1}: fetch={fetch_state.get('status')} process={process_state.get('status')} finalize={finalize_state.get('status')}"
            )
            if finalize_state.get("status") == "succeeded":
                break
        else:
            raise RuntimeError("Worker did not finalize in allotted passes")

        state = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        sources = state["sources"]
        events = state["events"]

        retry_event = next((e for e in events if e["event_type"] == "retry_after_honored"), None)
        if not retry_event:
            raise AssertionError("Missing retry_after_honored event")

        retry_source = next((s for s in sources if s["url"].endswith("/retry_after")), None)
        if not retry_source or retry_source["status"] != "fetched":
            raise AssertionError("retry_after source not fetched")
        if retry_source.get("attempt_count", 0) < 2:
            raise AssertionError("retry_after should require at least two attempts")
        retry_meta = retry_event.get("output_json") or {}
        if retry_meta.get("retry_after_seconds") != 2:
            raise AssertionError("retry_after_seconds not honored")

        rate_events = [e for e in events if e["event_type"] == "domain_rate_limited"]
        if not rate_events:
            raise AssertionError("Missing domain_rate_limited event")
        if not any((e.get("output_json") or {}).get("waited_ms", 0) > 0 for e in rate_events):
            raise AssertionError("domain_rate_limited events missing waited_ms")
        if not any((e.get("output_json") or {}).get("waited_ms", 0) >= 150 for e in rate_events):
            raise AssertionError("domain_rate_limited wait too small to prove min-delay")

        fetch_started = [
            (idx, e)
            for idx, e in enumerate(events)
            if e["event_type"] == "fetch_started" and (e.get("input_json") or {}).get("url", "").startswith(base)
        ]
        fetch_succeeded = [e for e in events if e["event_type"] == "fetch_succeeded"]
        if len(fetch_started) < 4 or len(fetch_succeeded) < 4:
            raise AssertionError("Expected fetch_started/fetch_succeeded for all sources")

        slow1_idx = next((idx for idx, e in fetch_started if (e.get("input_json") or {}).get("url", "").endswith("slow_1")), None)
        slow2_idx = next((idx for idx, e in fetch_started if (e.get("input_json") or {}).get("url", "").endswith("slow_2")), None)
        if slow1_idx is None or slow2_idx is None:
            raise AssertionError("Missing fetch_started for slow endpoints")
        if slow2_idx <= slow1_idx:
            raise AssertionError("Expected slow_2 fetch to start after slow_1 fetch")

        slow1_success_idx = next(
            (
                idx
                for idx, e in enumerate(events)
                if e["event_type"] == "fetch_succeeded"
                and (e.get("input_json") or {}).get("url", "").endswith("slow_1")
            ),
            None,
        )

        if slow1_success_idx is not None and slow2_idx <= slow1_success_idx:
            raise AssertionError("Expected slow_2 fetch to begin after slow_1 success")

        baseline_event_count = len(events)
        baseline_sources = len(sources)

        for _ in range(2):
            run_worker_once(py_exe, env_overrides)
            time.sleep(0.3)

        state_after = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        if len(state_after["events"]) != baseline_event_count:
            raise AssertionError("Idempotency violated: new events after rerun")
        if len(state_after["sources"]) != baseline_sources:
            raise AssertionError("Idempotency violated: source count changed")

        git_exe = shutil.which("git") or r"C:\\Program Files\\Git\\cmd\\git.exe"
        postcheck_lines = []
        rc_status, status_out, _ = run_cmd([git_exe, "status", "-sb"])
        if rc_status == 0:
            postcheck_lines.append(f"== git status -sb ==\n{status_out}")
        rc_log, log_out, _ = run_cmd([git_exe, "log", "-1", "--decorate"])
        if rc_log == 0:
            postcheck_lines.append(f"== git log -1 --decorate ==\n{log_out}")
        rc_alembic, alembic_out, _ = run_cmd([sys.executable, "-m", "alembic", "current"])
        if rc_alembic == 0:
            postcheck_lines.append(f"== alembic current ==\n{alembic_out}")

        write_artifacts(openapi_body, postcheck_lines)
        log("=== PROOF COMPLETE ===")
        return_code = 0

    finally:
        stop_fixture_server(fixture_server)

    return return_code


if __name__ == "__main__":
    sys.exit(main())

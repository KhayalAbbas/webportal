import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_3_canonicalization_and_dedupe.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_3_openapi.json"
PRECHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_3_preflight.txt"
POSTCHECK_ARTIFACT = ARTIFACT_DIR / "phase_4_3_postcheck.txt"

LOG_LINES: list[str] = []


class CanonicalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.rstrip("/") == "":
            self._write_html(200, "<h1>root</h1>")
            return

        if path.rstrip("/") == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:8765/canonical/")
            self.end_headers()
            return

        if path.rstrip("/") == "/canonical":
            html = """
            <html>
                <head><title>Canonical Fixture</title></head>
                <body>
                    <h1>Investment Firms</h1>
                    <ul>
                        <li>Cedar Ridge Capital</li>
                        <li>Silver Oak Advisors</li>
                    </ul>
                </body>
            </html>
            """
            self._write_html(200, html)
            return

        self._write_html(404, "<h1>not found</h1>")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _write_html(self, status: int, body: str) -> None:
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def start_fixture_server(port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), CanonicalHandler)
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


def preflight() -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    log("--- PRE-FLIGHT ---")
    py_ver = sys.version.replace("\n", " ")
    lines: list[str] = [f"Python: {py_ver}"]

    rc_pyver, pyver_out, pyver_err = run_cmd([sys.executable, "-V"])
    lines.append(f"python -V: {pyver_out}" if rc_pyver == 0 else f"python -V unavailable (rc={rc_pyver}): {pyver_err}")

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
    lines.append(
        f"alembic current: {alembic_out}" if rc_alembic == 0 else f"alembic current unavailable (rc={rc_alembic}): {alembic_err}"
    )

    rc_heads, heads_out, heads_err = run_cmd([sys.executable, "-m", "alembic", "heads"])
    lines.append(
        f"alembic heads: {heads_out}" if rc_heads == 0 else f"alembic heads unavailable (rc={rc_heads}): {heads_err}"
    )

    dsn = os.environ.get("ATS_DSN", "postgresql://postgres:postgres@localhost:5432/ats_db")
    rc_db, db_out, db_err = run_cmd(
        [
            sys.executable,
            "-c",
            "import os, psycopg2; dsn=os.environ.get('ATS_DSN','postgresql://postgres:postgres@localhost:5432/ats_db'); c=psycopg2.connect(dsn); cur=c.cursor(); cur.execute('select 1'); print('DB_OK', cur.fetchone()); c.close()",
        ],
    )
    lines.append(f"DB ping ({dsn}): {db_out}" if rc_db == 0 else f"DB ping failed (rc={rc_db}): {db_err}")

    log("\n".join(lines))
    log("--- PRE-FLIGHT DONE ---")

    return {
        "lines": lines,
        "rcs": {
            "python": rc_pyver,
            "git": 0 if "git status -sb" in git_line else 1,
            "alembic": rc_alembic,
            "heads": rc_heads,
            "db": rc_db,
        },
        "alembic_current": alembic_out,
        "alembic_heads": heads_out,
    }


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


def wait_for_api(api_base: str, server_proc: subprocess.Popen | None) -> requests.Response:
    for attempt in range(20):
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
    raise RuntimeError("API did not become ready after 20s")


async def fetch_db_state(tenant_id: str, run_id: str) -> dict:
    async with async_session_maker() as session:
        src_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, url, url_normalized, original_url, canonical_final_url,
                           canonical_source_id, status, content_hash, http_final_url,
                           meta
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
                    SELECT event_type, status, input_json, output_json
                    FROM research_events
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                      AND event_type IN ('canonicalize','redirect_resolved','canonical_dedupe','fetch_started','fetch_succeeded','fetch_failed')
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


def write_artifacts(openapi_body: dict) -> None:
    raise RuntimeError("Use write_all_artifacts instead")


def write_all_artifacts(openapi_body: dict | None, preflight_lines: list[str], postcheck_lines: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")

    if preflight_lines:
        PRECHECK_ARTIFACT.write_text("\n".join(preflight_lines), encoding="utf-8")
        log(f"Preflight saved to {PRECHECK_ARTIFACT}")

    if openapi_body is not None:
        OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
        log(f"OpenAPI snapshot saved to {OPENAPI_ARTIFACT}")

    if postcheck_lines:
        POSTCHECK_ARTIFACT.write_text("\n".join(postcheck_lines), encoding="utf-8")
        log(f"Postcheck saved to {POSTCHECK_ARTIFACT}")


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
    fixture_server: ThreadingHTTPServer | None = None

    log("=== PHASE 4.3 CANONICALIZATION + DEDUPE PROOF ===")
    log(f"API Base: {api_base}")
    log(f"Tenant: {tenant_id}")

    preflight_result = preflight()
    preflight_lines: list[str] = preflight_result.get("lines", [])
    postcheck_lines: list[str] = []
    openapi_body: dict | None = None
    return_code = 1

    try:
        openapi_resp: requests.Response | None = None
        try:
            existing = requests.get(urljoin(api_base, "/openapi.json"), timeout=2)
            existing.raise_for_status()
            openapi_resp = existing
            log("Existing API detected; skipping local uvicorn start")
        except Exception:
            log("Starting local uvicorn for proof...")
            server_proc = start_server(py_exe, api_port)

        openapi_resp = openapi_resp or wait_for_api(api_base, server_proc)
        openapi_body = openapi_resp.json()
        preflight_lines.append(f"GET {api_base}/openapi.json status={openapi_resp.status_code} length={len(openapi_resp.text)}")

        if "canonical_source_id" not in json.dumps(openapi_body):
            log("OpenAPI missing canonical fields; starting local uvicorn for fresh schema")
            stop_server(server_proc)
            api_port += 1
            api_base = f"http://localhost:{api_port}"
            server_proc = start_server(py_exe, api_port)
            openapi_resp = wait_for_api(api_base, server_proc)
            openapi_body = openapi_resp.json()
            preflight_lines.append(f"GET {api_base}/openapi.json status={openapi_resp.status_code} length={len(openapi_resp.text)} (local)")

        log("API ready; openapi.json loaded")

        fixture_server = start_fixture_server()
        log("Fixture HTTP server started on 127.0.0.1:8765")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.3-Canonical-{uuid.uuid4().hex[:6]}",
            "description": "Proof canonical URL + dedupe",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        source_urls = [
            "http://127.0.0.1:8765/canonical",
            "http://127.0.0.1:8765/redirect?utm=1",
        ]
        source_ids: list[str] = []
        for idx, url in enumerate(source_urls, start=1):
            payload = {"title": f"Fixture-{idx}", "url": url}
            src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
            source_ids.append(src["id"])
            log(f"URL source attached: {src['id']} {url}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        for attempt in range(4):
            run_worker_once(py_exe)
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
            raise RuntimeError("Finalize step did not complete")

        db_state = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        sources = db_state["sources"]
        if len(sources) != 2:
            raise RuntimeError(f"Expected 2 sources, got {len(sources)}")

        canonical_ids = {s["canonical_source_id"] for s in sources}
        if len(canonical_ids - {None}) != 1:
            raise RuntimeError(f"Expected a single canonical_source_id, got {canonical_ids}")

        canonical_source = next((s for s in sources if s["canonical_source_id"] == s["id"]), None)
        duplicate_source = next((s for s in sources if s.get("canonical_source_id") and s["canonical_source_id"] != s["id"]), None)
        if not canonical_source or not duplicate_source:
            raise RuntimeError("Missing canonical or duplicate source after dedupe")

        if canonical_source["canonical_source_id"] != canonical_source["id"]:
            raise RuntimeError("Canonical source must point to itself")
        if not canonical_source.get("content_hash"):
            raise RuntimeError("Canonical source missing content_hash")
        if duplicate_source["canonical_source_id"] != canonical_source["id"]:
            raise RuntimeError("Duplicate source must reference canonical source id")
        if duplicate_source.get("content_hash") is not None:
            raise RuntimeError("Duplicate source should have null content_hash after dedupe")
        deduped_flag = bool(duplicate_source.get("meta", {}).get("fetch_info", {}).get("deduped"))
        if not deduped_flag:
            raise RuntimeError("Duplicate source meta.fetch_info.deduped should be true")

        if duplicate_source["status"] != "processed":
            raise RuntimeError(f"Duplicate source should be processed, got {duplicate_source['status']}")

        if not canonical_source.get("canonical_final_url"):
            raise RuntimeError("Missing canonical_final_url on canonical source")

        log(f"Canonical source: {canonical_source}")
        log(f"Duplicate source: {duplicate_source}")

        if not preflight_result.get("rcs", {}).get("db") == 0:
            raise RuntimeError("Preflight DB ping failed")
        if preflight_result.get("rcs", {}).get("alembic") != 0 or preflight_result.get("rcs", {}).get("heads") != 0:
            raise RuntimeError("Preflight alembic checks failed")
        if preflight_result.get("alembic_current") and preflight_result.get("alembic_heads"):
            if preflight_result["alembic_current"].split()[0] not in preflight_result["alembic_heads"]:
                raise RuntimeError("Alembic current is not at head")

        event_types = [e["event_type"] for e in db_state["events"]]
        for expected_evt in ["canonicalize", "redirect_resolved", "canonical_dedupe"]:
            if expected_evt not in event_types:
                raise RuntimeError(f"Missing expected event {expected_evt}")

        baseline_event_counts = Counter(event_types)
        baseline_fetch_counts = Counter(e["event_type"] for e in db_state["events"] if e["event_type"].startswith("fetch_"))

        postcheck_lines.extend(
            [
                f"Run: {run_id}",
                f"Canonical source: id={canonical_source['id']} status={canonical_source['status']} content_hash={canonical_source['content_hash']} canonical_final_url={canonical_source.get('canonical_final_url')}",
                f"Duplicate source: id={duplicate_source['id']} status={duplicate_source['status']} canonical_source_id={duplicate_source['canonical_source_id']} content_hash={duplicate_source['content_hash']} deduped={deduped_flag}",
            ]
        )

        log("--- IDEMPOTENCY CHECK (no new inputs) ---")
        snapshot_events = len(db_state["events"])
        snapshot_sources = len(sources)
        for attempt in range(3):
            run_worker_once(py_exe)
            time.sleep(0.5)
        db_state_after = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        after_fetch_counts = Counter(e["event_type"] for e in db_state_after["events"] if e["event_type"].startswith("fetch_"))
        after_event_counts = Counter(e["event_type"] for e in db_state_after["events"])

        log(
            f"DB baseline: sources={snapshot_sources} events={snapshot_events} / DB after: sources={len(db_state_after['sources'])} events={len(db_state_after['events'])}"
        )
        log(f"Fetch events baseline: {dict(baseline_fetch_counts)} / after: {dict(after_fetch_counts)}")
        log(f"Event summary baseline: {dict(baseline_event_counts)} / after: {dict(after_event_counts)}")

        if len(db_state_after["sources"]) != snapshot_sources:
            raise RuntimeError("Idempotency failed: source count changed")
        if len(db_state_after["events"]) != snapshot_events:
            raise RuntimeError("Idempotency failed: event count changed")
        if after_fetch_counts != baseline_fetch_counts:
            raise RuntimeError("Idempotency failed: fetch event counts changed")

        postcheck_lines.extend(
            [
                f"DB baseline: sources={snapshot_sources} events={snapshot_events}",
                f"DB after: sources={len(db_state_after['sources'])} events={len(db_state_after['events'])}",
                f"Fetch events baseline: {dict(baseline_fetch_counts)}",
                f"Fetch events after: {dict(after_fetch_counts)}",
                f"Event summary baseline: {dict(baseline_event_counts)}",
                f"Event summary after: {dict(after_event_counts)}",
            ]
        )

        if openapi_body and "canonical_source_id" not in json.dumps(openapi_body):
            raise RuntimeError("canonical_source_id missing from OpenAPI schema")

        log("=== PROOF COMPLETE ===")
        return_code = 0

    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")

    finally:
        stop_fixture_server(fixture_server)
        stop_server(server_proc)
        write_all_artifacts(openapi_body, preflight_lines, postcheck_lines)


    return return_code


if __name__ == "__main__":
    raise SystemExit(main())

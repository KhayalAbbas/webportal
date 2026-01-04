import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import psycopg2
import requests
from dotenv import load_dotenv

sys.path.append(os.getcwd())
from app.core.config import settings  # noqa: E402
from scripts.proofs.phase_4_13_local_http_server import find_free_server

API_DEFAULT = "http://127.0.0.1:8006"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
PROOF_ARTIFACT = ARTIFACT_DIR / "phase_4_13_proof.txt"

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = str(msg)
    print(line)
    LOG_LINES.append(line)


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


@contextmanager
def start_fixture_server(host: str = "127.0.0.1"):
    server = find_free_server(host)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
    log(f"Fixture server started at {base_url}")
    try:
        yield base_url
    finally:
        server.shutdown()
        log("Fixture server stopped")


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
    resp = requests.request(method, url, headers=headers, json=payload, timeout=30)
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
                SELECT id, url, url_normalized, status, attempt_count, next_retry_at, meta, created_at, last_error,
                       error_message, fetched_at, content_hash, http_status_code, http_final_url, canonical_final_url,
                       http_headers
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


def run_worker_once(py_exe: str, env_overrides: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.getcwd())
    if env_overrides:
        env.update(env_overrides)
    subprocess.run(
        [py_exe, "-m", "app.workers.company_research_worker", "--once"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def write_proof(proof_passed: bool, postcheck_lines: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    footer = "PASS" if proof_passed else "FAIL"
    body = LOG_LINES + ["== assertions =="] + postcheck_lines + [f"PROOF_RESULT={footer}"]
    PROOF_ARTIFACT.write_text("\n".join(body), encoding="utf-8")
    log(f"Proof artifact written to {PROOF_ARTIFACT}")


def assert_true(condition: bool, message: str, post: list[str]) -> None:
    if not condition:
        raise AssertionError(message)
    post.append(f"PASS: {message}")


def main() -> int:
    load_dotenv()
    api_base = os.getenv("BASE_URL", API_DEFAULT)
    tenant_id = os.getenv("API_TENANT_ID", TENANT_DEFAULT)
    email = os.getenv("API_EMAIL", EMAIL_DEFAULT)
    password = os.getenv("API_PASSWORD", PASSWORD_DEFAULT)
    py_exe = os.getenv("PY_EXE", sys.executable)

    proof_passed = False
    postcheck: list[str] = []

    try:
        with start_fixture_server() as base_url:
            token = login(api_base, tenant_id, email, password)
            headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

            role_id = select_role(api_base, headers)
            run_payload = {
                "role_mandate_id": role_id,
                "name": f"Phase4.13-Acq-{uuid.uuid4().hex[:6]}",
                "description": "Phase 4.13 acquisition policy proof",
                "sector": "finance",
                "region_scope": ["US"],
            }
            run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
            run_id = run["id"]
            log(f"Run created: {run_id}")

            purged = purge_jobs(tenant_id)
            log(f"Purged {purged} company_research_jobs before start")

            redirect_url = f"{base_url}/redirect1"
            png_url = f"{base_url}/png"
            big_url = f"{base_url}/big"
            blocked_url = f"{base_url}/blocked"
            etag_url = f"{base_url}/html_etag"
            rate_url = f"{base_url}/rate_limited"

            urls = [
                ("Redirect", redirect_url),
                ("PNG", png_url),
                ("Big", big_url),
                ("Blocked", blocked_url),
                ("ETag", etag_url),
                ("RateLimit", rate_url),
            ]

            for title, url in urls:
                payload = {"title": title, "url": url}
                src = call_api("POST", api_base, f"/company-research/runs/{run_id}/sources/url", headers, payload=payload)
                log(f"Attached source {src['id']} -> {url}")

            start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
            job_id = start_resp.get("id") or start_resp.get("job_id")
            log(f"Run started (job {job_id})")

            # Drive worker passes to exercise retries and conditional fetch
            for idx in range(6):
                try:
                    run_worker_once(py_exe, {})
                    log(f"Worker pass {idx + 1} done")
                except subprocess.CalledProcessError as exc:  # noqa: PERF203
                    log(f"Worker pass {idx + 1} failed rc={exc.returncode}: {exc.stderr[:200]}")
                time.sleep(1.2)

            state = fetch_db_state(tenant_id, run_id)
            sources = state["sources"]
            postcheck.append(f"sources_count={len(sources)}")
            postcheck.append(f"job_id={job_id}")

            by_url = {row["url"]: row for row in sources}

            assert_true(redirect_url in by_url, "redirect source present", postcheck)
            assert_true(png_url in by_url, "png source present", postcheck)
            assert_true(big_url in by_url, "big source present", postcheck)
            assert_true(blocked_url in by_url, "blocked source present", postcheck)
            assert_true(etag_url in by_url, "etag source present", postcheck)
            assert_true(rate_url in by_url, "rate limit source present", postcheck)

            redirect_src = by_url[redirect_url]
            png_src = by_url[png_url]
            big_src = by_url[big_url]
            blocked_src = by_url[blocked_url]
            etag_src = by_url[etag_url]
            rate_src = by_url[rate_url]

            # Redirect chain recorded and final URL resolved
            meta = redirect_src.get("meta") or {}
            fetch_info = meta.get("fetch_info") or {}
            http_info = fetch_info.get("http") or {}
            redirect_chain = http_info.get("redirect_chain") or []
            assert_true(
                redirect_src.get("status") == "fetched" and http_info.get("final_url", "").endswith("/final"),
                "redirect final url captured",
                postcheck,
            )
            assert_true(len(redirect_chain) == 2 and redirect_chain[-1].get("to", "").endswith("/final"), "redirect chain stored", postcheck)

            # Unsupported content-type rejected
            assert_true(
                png_src.get("status") == "failed" and (png_src.get("last_error") or png_src.get("error_message")) == "unsupported_content_type",
                "unsupported content type blocked",
                postcheck,
            )

            # Max-bytes enforcement
            big_meta = (big_src.get("meta") or {}).get("fetch_info") or {}
            assert_true(
                big_src.get("status") == "failed" and (big_src.get("last_error") or big_src.get("error_message")) == "fetch_too_large",
                "max bytes enforcement triggered",
                postcheck,
            )
            assert_true((big_meta.get("bytes_read") or 0) > 2_000_000, "bytes_read recorded for oversized fetch", postcheck)

            # Robots disallow respected
            assert_true(
                blocked_src.get("status") == "failed" and (blocked_src.get("last_error") or blocked_src.get("error_message")) == "robots_disallowed",
                "robots disallow enforced",
                postcheck,
            )

            # Retry-After honored and eventual success
            assert_true(rate_src.get("attempt_count", 0) >= 2, "rate-limited source retried", postcheck)
            assert_true(rate_src.get("status") == "fetched" and rate_src.get("http_status_code") == 200, "rate-limited source eventually fetched", postcheck)

            # Conditional GET yields not_modified path
            etag_meta = (etag_src.get("meta") or {}).get("fetch_info") or {}
            validators = (etag_src.get("meta") or {}).get("validators") or {}
            assert_true(etag_src.get("status") == "fetched", "etag source fetched", postcheck)
            assert_true(bool(validators.get("etag")) and bool(validators.get("last_modified")), "etag validators stored", postcheck)
            assert_true(etag_meta.get("not_modified") is True or etag_meta.get("extraction_method") == "not_modified", "304 not_modified recorded", postcheck)

            proof_passed = True
            write_proof(proof_passed, postcheck)
            return 0

    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        write_proof(proof_passed, postcheck)
        return 1


if __name__ == "__main__":
    import subprocess

    raise SystemExit(main())

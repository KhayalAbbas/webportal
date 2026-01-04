import json
import os
import subprocess
import sys
import threading
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
from scripts.proofs.phase_4_13_local_http_server import find_free_server  # noqa: E402

API_DEFAULT = "http://127.0.0.1:8006"
TENANT_DEFAULT = "b3909011-8bd3-439d-a421-3b70fae124e9"
EMAIL_DEFAULT = "admin@test.com"
PASSWORD_DEFAULT = "admin123"

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
PROOF_ARTIFACT = ARTIFACT_DIR / "phase_5_1_proof.txt"
SRC_FIRST_ARTIFACT = ARTIFACT_DIR / "phase_5_1_sources_after_first_run.json"
SRC_SECOND_ARTIFACT = ARTIFACT_DIR / "phase_5_1_sources_after_second_run.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_5_1_db_excerpt.sql.txt"
FIXTURE_NOTES_ARTIFACT = ARTIFACT_DIR / "phase_5_1_fixture_server_notes.txt"
API_CREATE_ARTIFACT = ARTIFACT_DIR / "phase_5_1_api_create_run.json"
API_ADD_SOURCES_ARTIFACT = ARTIFACT_DIR / "phase_5_1_api_add_sources.json"
API_SOURCES_AFTER_ARTIFACT = ARTIFACT_DIR / "phase_5_1_api_sources_after.json"

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


def call_api(method: str, api_base: str, path: str, headers: dict[str, str], payload=None):
    url = urljoin(api_base, path)
    resp = requests.request(method, url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"API {method} {path} failed {resp.status_code}: {resp.text[:200]}")
    if resp.text:
        return resp.json()
    return None


def select_role(api_base: str, headers: dict[str, str]) -> str:
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


def write_proof(proof_passed: bool, postcheck: list[str]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    footer = "PASS" if proof_passed else "FAIL"
    body = LOG_LINES + ["== assertions =="] + postcheck + [f"PROOF_RESULT={footer}"]
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
                "name": f"Phase5.1-Extract-{uuid.uuid4().hex[:6]}",
                "description": "Phase 5.1 extraction quality proof",
                "sector": "software",
                "region_scope": ["US"],
            }
            run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
            run_id = run["id"]
            log(f"Run created: {run_id}")

            purged = purge_jobs(tenant_id)
            log(f"Purged {purged} company_research_jobs before start")

            url_payloads = [
                {"title": "content_html", "url": f"{base_url}/content_html"},
                {"title": "content_html_variant", "url": f"{base_url}/content_html_variant"},
                {"title": "thin_html", "url": f"{base_url}/thin_html"},
                {"title": "login_html", "url": f"{base_url}/login_html"},
                {"title": "fixture_pdf", "url": f"{base_url}/pdf"},
            ]
            added_sources: list[dict[str, Any]] = []
            for payload in url_payloads:
                doc = call_api(
                    "POST",
                    api_base,
                    f"/company-research/runs/{run_id}/sources/url",
                    headers,
                    payload=payload,
                )
                added_sources.append(doc)
                log(f"Added URL source {doc['title']} -> {doc['url']}")
            API_ADD_SOURCES_ARTIFACT.write_text(json.dumps(added_sources, indent=2), encoding="utf-8")

            FIXTURE_NOTES_ARTIFACT.write_text(
                "\n".join(
                    [
                        f"base_url={base_url}",
                        "endpoints=/content_html,/content_html_variant,/thin_html,/login_html,/pdf",
                    ]
                ),
                encoding="utf-8",
            )

            job = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
            log(f"Job enqueued: {job['id']}")

            rc_worker, worker_out, worker_err = run_cmd([py_exe, "-m", "app.workers.company_research_worker", "--once"])
            log(f"worker rc={rc_worker} out={worker_out[:200]} err={worker_err[:200]}")
            assert_true(rc_worker == 0, "worker completed first pass", postcheck)

            sources = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
            log(f"Fetched {len(sources)} sources after first extraction")
            SRC_FIRST_ARTIFACT.write_text(json.dumps(sources, indent=2), encoding="utf-8")

            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            extract_step = next(s for s in steps if s["step_key"] == "extract_url_sources")
            process_step = next(s for s in steps if s["step_key"] == "process_sources")
            assert_true(extract_step["status"] == "succeeded", "extract step succeeded", postcheck)
            assert_true(process_step["status"] in {"succeeded", "pending", "queued"}, "process step present", postcheck)
            assert_true(extract_step["step_order"] < process_step["step_order"], "extract before process ordering", postcheck)

            by_title: dict[str, Any] = {src.get("title") or src.get("url"): src for src in sources}

            good = by_title["content_html"]
            good_extraction = (good.get("meta") or {}).get("extraction", {})
            good_flags = (good.get("meta") or {}).get("quality_flags", {})
            assert_true(good_extraction.get("decision") == "accept", "content_html accepted", postcheck)
            assert_true(good_extraction.get("word_count", 0) >= 150, "content_html word_count >= 150", postcheck)
            assert_true(good_extraction.get("reason_codes") == [], "content_html has no reason codes", postcheck)
            assert_true(not any(good_flags.values()), "content_html quality flags clear", postcheck)

            variant = by_title["content_html_variant"]
            variant_extraction = (variant.get("meta") or {}).get("extraction", {})
            variant_flags = (variant.get("meta") or {}).get("quality_flags", {})
            assert_true(variant_extraction.get("decision") == "flag", "variant flagged", postcheck)
            assert_true("FLAG_DUPLICATE_TEMPLATE" in (variant_extraction.get("reason_codes") or []), "variant flagged duplicate template", postcheck)
            assert_true(bool(variant_flags.get("is_duplicate_template")), "variant quality flag duplicate_template set", postcheck)

            thin = by_title["thin_html"]
            thin_extraction = (thin.get("meta") or {}).get("extraction", {})
            thin_flags = (thin.get("meta") or {}).get("quality_flags", {})
            assert_true(thin_extraction.get("decision") == "reject", "thin_html rejected", postcheck)
            assert_true(bool(thin_flags.get("is_thin")), "thin_html flagged as thin", postcheck)
            assert_true("REJECT_THIN_CONTENT" in (thin_extraction.get("reason_codes") or []), "thin_html reason reject_thin", postcheck)

            login_doc = by_title["login_html"]
            login_extraction = (login_doc.get("meta") or {}).get("extraction", {})
            login_flags = (login_doc.get("meta") or {}).get("quality_flags", {})
            reasons = login_extraction.get("reason_codes") or []
            assert_true(login_extraction.get("decision") in {"flag", "reject"}, "login_html flagged or rejected", postcheck)
            assert_true("FLAG_PAYWALL_OR_LOGIN" in reasons, "login_html paywall flag set", postcheck)
            assert_true(bool(login_flags.get("is_paywall_or_login")), "login_html quality flag paywall/login set", postcheck)

            pdf = by_title["fixture_pdf"]
            pdf_extraction = (pdf.get("meta") or {}).get("extraction", {})
            pdf_flags = (pdf.get("meta") or {}).get("quality_flags", {})
            assert_true(pdf_extraction.get("decision") in {"reject", "flag", "accept"}, "pdf decision recorded", postcheck)
            assert_true("word_count" in pdf_extraction, "pdf has word_count", postcheck)
            assert_true(pdf_flags.get("is_unextractable_pdf") is False, "pdf not marked unextractable", postcheck)

            # Run worker again to prove idempotency
            rc_worker2, worker_out2, worker_err2 = run_cmd([py_exe, "-m", "app.workers.company_research_worker", "--once"])
            log(f"worker second rc={rc_worker2} out={worker_out2[:200]} err={worker_err2[:200]}")
            assert_true(rc_worker2 == 0, "worker completed second pass", postcheck)

            sources_second = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
            log(f"Fetched {len(sources_second)} sources after second extraction")
            SRC_SECOND_ARTIFACT.write_text(json.dumps(sources_second, indent=2), encoding="utf-8")

            by_title_second: dict[str, Any] = {src.get("title") or src.get("url"): src for src in sources_second}
            for title, first in by_title.items():
                second = by_title_second[title]
                first_meta = (first.get("meta") or {}).get("extraction", {})
                second_meta = (second.get("meta") or {}).get("extraction", {})
                assert_true(first_meta.get("text_hash") == second_meta.get("text_hash"), f"idempotent hash for {title}", postcheck)
                assert_true(first_meta.get("source_material_hash") == second_meta.get("source_material_hash"), f"idempotent material hash for {title}", postcheck)

            # DB excerpt
            dsn = _get_dsn()
            query_sources = """
            SELECT
              id,
              title,
              url,
              mime_type,
              status,
              content_hash,
              fetched_at,
              meta->'extraction' AS extraction,
              meta->'quality_flags' AS quality_flags
            FROM source_documents
            WHERE company_research_run_id = %s
            ORDER BY title;
            """
            query_events = """SELECT event_type, status, created_at, input_json, output_json FROM research_events WHERE company_research_run_id = %s AND event_type IN ('extract_source_content','process_sources') ORDER BY created_at;"""
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(query_sources, (run_id,))
                    rows = cur.fetchall()
                    cur.execute(query_events, (run_id,))
                    events = cur.fetchall()
                    DB_EXCERPT_ARTIFACT.write_text(
                        "\n".join([
                            query_sources.strip(),
                            "-- rows:",
                            json.dumps(rows, default=str, indent=2),
                            "",
                            query_events.strip(),
                            "-- events:",
                            json.dumps(events, default=str, indent=2),
                        ]),
                        encoding="utf-8",
                    )

            API_CREATE_ARTIFACT.write_text(json.dumps(run, indent=2), encoding="utf-8")
            API_SOURCES_AFTER_ARTIFACT.write_text(json.dumps(sources_second, indent=2), encoding="utf-8")

            proof_passed = True
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
    finally:
        write_proof(proof_passed, postcheck)

    return 0 if proof_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

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
PROOF_ARTIFACT = ARTIFACT_DIR / "phase_5_2_proof.txt"
SRC_FIRST_ARTIFACT = ARTIFACT_DIR / "phase_5_2_sources_after_first_run.json"
SRC_SECOND_ARTIFACT = ARTIFACT_DIR / "phase_5_2_sources_after_second_run.json"
DB_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_5_2_db_excerpt.sql.txt"
FIXTURE_NOTES_ARTIFACT = ARTIFACT_DIR / "phase_5_2_fixture_server_notes.txt"
OPENAPI_EXCERPT_ARTIFACT = ARTIFACT_DIR / "phase_5_2_openapi_company_research_excerpt.txt"
API_SOURCES_AFTER_ARTIFACT = ARTIFACT_DIR / "phase_5_2_api_sources_after.json"

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


def fetch_openapi_excerpt(api_base: str) -> None:
    resp = requests.get(urljoin(api_base, "/openapi.json"), timeout=10)
    resp.raise_for_status()
    paths = resp.json().get("paths", {})
    entries: list[str] = []
    for path, methods in paths.items():
        if "company-research" not in path:
            continue
        for method, spec in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            summary = spec.get("summary") or spec.get("operationId") or ""
            entries.append(f"{method.upper()} {path} - {summary}")
    entries = sorted(entries)
    OPENAPI_EXCERPT_ARTIFACT.write_text("\n".join(entries), encoding="utf-8")


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
                "name": f"Phase5.2-Dedupe-{uuid.uuid4().hex[:6]}",
                "description": "Phase 5.2 duplicate/template + junk classification proof",
                "sector": "software",
                "region_scope": ["US"],
            }
            run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
            run_id = run["id"]
            log(f"Run created: {run_id}")

            url_payloads = [
                {"title": "content_html", "url": f"{base_url}/content_html"},
                {"title": "content_html_variant", "url": f"{base_url}/content_html_variant"},
                {"title": "thin_html", "url": f"{base_url}/thin_html"},
                {"title": "login_html", "url": f"{base_url}/login_html"},
                {"title": "boilerplate_long_html", "url": f"{base_url}/boilerplate_long_html"},
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

            FIXTURE_NOTES_ARTIFACT.write_text(
                "\n".join([
                    f"base_url={base_url}",
                    "endpoints=/content_html,/content_html_variant,/thin_html,/login_html,/boilerplate_long_html,/pdf",
                ]),
                encoding="utf-8",
            )

            call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)

            # Run worker passes until classify step is done (bounded to avoid runaway)
            for i in range(1, 4):
                rc_worker, worker_out, worker_err = run_cmd([py_exe, "-m", "app.workers.company_research_worker", "--once"])
                log(f"worker pass {i} rc={rc_worker} out={worker_out[:160]} err={worker_err[:160]}")
                assert_true(rc_worker == 0, f"worker pass {i} completed", postcheck)
                steps_now = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
                classify_now = next(s for s in steps_now if s["step_key"] == "classify_sources")
                if classify_now["status"] == "succeeded":
                    break

            sources = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
            SRC_FIRST_ARTIFACT.write_text(json.dumps(sources, indent=2), encoding="utf-8")
            log(f"Fetched {len(sources)} sources after first run")

            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            extract_step = next(s for s in steps if s["step_key"] == "extract_url_sources")
            classify_step = next(s for s in steps if s["step_key"] == "classify_sources")
            process_step = next(s for s in steps if s["step_key"] == "process_sources")
            assert_true(extract_step["step_order"] < classify_step["step_order"] < process_step["step_order"], "extract -> classify -> process ordering", postcheck)
            assert_true(classify_step["status"] == "succeeded", "classify step succeeded", postcheck)

            by_title_first: dict[str, Any] = {src.get("title") or src.get("url"): src for src in sources}

            def _meta_first(title: str) -> dict[str, Any]:
                return (by_title_first[title].get("meta") or {})

            content_meta = _meta_first("content_html")
            variant_meta = _meta_first("content_html_variant")
            boiler_meta = _meta_first("boilerplate_long_html")
            thin_meta = _meta_first("thin_html")
            login_meta = _meta_first("login_html")
            pdf_meta = _meta_first("fixture_pdf")

            def _flags(m: dict[str, Any]) -> dict[str, Any]:
                return m.get("quality_flags") or {}

            def _extract(m: dict[str, Any]) -> dict[str, Any]:
                return m.get("extraction") or {}

            content_flags = _flags(content_meta)
            variant_flags = _flags(variant_meta)
            boiler_flags = _flags(boiler_meta)
            thin_flags = _flags(thin_meta)
            login_flags = _flags(login_meta)
            pdf_flags = _flags(pdf_meta)

            content_extraction = _extract(content_meta)
            variant_extraction = _extract(variant_meta)
            boiler_extraction = _extract(boiler_meta)
            thin_extraction = _extract(thin_meta)
            login_extraction = _extract(login_meta)
            pdf_extraction = _extract(pdf_meta)

            pair = [by_title_first["content_html"], by_title_first["content_html_variant"]]
            primary = next(p for p in pair if not ((p.get("meta") or {}).get("quality_flags") or {}).get("is_duplicate_template"))
            duplicate = next(p for p in pair if ((p.get("meta") or {}).get("quality_flags") or {}).get("is_duplicate_template"))
            primary_meta = primary.get("meta") or {}
            duplicate_meta = duplicate.get("meta") or {}
            primary_extraction = _extract(primary_meta)
            duplicate_extraction = _extract(duplicate_meta)
            primary_flags = _flags(primary_meta)
            duplicate_flags = _flags(duplicate_meta)

            assert_true(primary_extraction.get("decision") == "accept", "primary content accepted", postcheck)
            assert_true(duplicate_flags.get("is_duplicate_template") is True, "secondary marked duplicate", postcheck)
            assert_true(duplicate_extraction.get("decision") in {"flag", "reject"}, "duplicate not accepted", postcheck)
            assert_true(duplicate_flags.get("duplicate_group_key") is not None, "duplicate group key set", postcheck)
            assert_true(duplicate_flags.get("duplicate_primary_source_id") == primary.get("id"), "duplicate primary id points to primary", postcheck)
            assert_true(duplicate_extraction.get("signature_prefix_2k") == primary_extraction.get("signature_prefix_2k"), "duplicate prefix signature matches", postcheck)
            assert_true(duplicate_extraction.get("text_hash") != primary_extraction.get("text_hash"), "duplicate hash differs", postcheck)

            assert_true(boiler_flags.get("is_boilerplate_dominant") is True, "boilerplate page flagged", postcheck)
            assert_true("FLAG_BOILERPLATE_DOMINANT" in (boiler_extraction.get("reason_codes") or []), "boilerplate reason present", postcheck)
            assert_true(boiler_extraction.get("decision") == "flag", "boilerplate decision flag", postcheck)

            assert_true(thin_flags.get("is_thin") is True, "thin_html thin flag", postcheck)
            assert_true(any(rc.startswith("REJECT_EXTREME_THIN") or rc.startswith("REJECT_EMPTY_TEXT") for rc in (thin_extraction.get("reason_codes") or [])), "thin_html rejected extreme thin", postcheck)

            assert_true(login_flags.get("is_paywall_or_login") is True, "login paywall flag", postcheck)
            assert_true("FLAG_PAYWALL_OR_LOGIN" in (login_extraction.get("reason_codes") or []), "login reason paywall", postcheck)

            assert_true("signature_prefix_2k" in content_extraction and "signature_tokens" in content_extraction, "signatures present", postcheck)
            assert_true(content_extraction.get("signature_prefix_2k") == variant_extraction.get("signature_prefix_2k"), "shared prefix signature for grouping", postcheck)

            # Run worker again to assert idempotency
            rc_worker2, worker_out2, worker_err2 = run_cmd([py_exe, "-m", "app.workers.company_research_worker", "--once"])
            log(f"worker2 rc={rc_worker2} out={worker_out2[:200]} err={worker_err2[:200]}")
            assert_true(rc_worker2 == 0, "worker completed second pass", postcheck)

            sources_second = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
            SRC_SECOND_ARTIFACT.write_text(json.dumps(sources_second, indent=2), encoding="utf-8")
            log(f"Fetched {len(sources_second)} sources after second run")

            by_title_second = {src.get("title") or src.get("url"): src for src in sources_second}
            for title, first in by_title_first.items():
                second = by_title_second[title]
                first_meta = _extract(_meta_first(title))
                second_meta = _extract(second.get("meta") or {})
                assert_true(first_meta.get("text_hash") == second_meta.get("text_hash"), f"idempotent text_hash for {title}", postcheck)
                assert_true(first_meta.get("signature_prefix_2k") == second_meta.get("signature_prefix_2k"), f"idempotent prefix sig for {title}", postcheck)
                assert_true(first_meta.get("signature_tokens") == second_meta.get("signature_tokens"), f"idempotent token sig for {title}", postcheck)
                assert_true(first_meta.get("decision") == second_meta.get("decision"), f"idempotent decision for {title}", postcheck)

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
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(query_sources, (run_id,))
                    rows = cur.fetchall()
                    DB_EXCERPT_ARTIFACT.write_text(
                        "\n".join([
                            query_sources.strip(),
                            "-- rows:",
                            json.dumps(rows, default=str, indent=2),
                        ]),
                        encoding="utf-8",
                    )

            API_SOURCES_AFTER_ARTIFACT.write_text(json.dumps(sources_second, indent=2), encoding="utf-8")
            fetch_openapi_excerpt(api_base)

            proof_passed = True
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
    finally:
        write_proof(proof_passed, postcheck)

    return 0 if proof_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

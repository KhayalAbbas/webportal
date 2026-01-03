import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
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
LOG_ARTIFACT = ARTIFACT_DIR / "phase_4_2_pdf_acquisition_and_extraction.log"
OPENAPI_ARTIFACT = ARTIFACT_DIR / "phase_4_2_openapi.json"
PREFLIGHT_ARTIFACT = ARTIFACT_DIR / "phase_4_2_preflight.txt"

# Deterministic PDF fixture containing two companies: "Blue River Bank" and "Nova Lending"
SAMPLE_PDF_B64 = "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCjIgMCBvYmoKPDwKL1R5cGUgL1BhZ2VzCi9Db3VudCAxCi9LaWRzIFszIDAgUl0KPj4KZW5kb2JqCjMgMCBvYmoKPDwKL1R5cGUgL1BhZ2UKL1BhcmVudCAyIDAgUgovTWVkaWFCb3ggWzAgMCA2MTIgNzkyXQovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMCA0IDAgUgo+Pgo+PgovQ29udGVudHMgNSAwIFIKPj4KZW5kb2JqCjQgMCBvYmoKPDwKL1R5cGUgL0ZvbnQKL1N1YnR5cGUgL1R5cGUxCi9CYXNlRm9udCAvSGVsdmV0aWNhCj4+CmVuZG9iago1IDAgb2JqCjw8Ci9MZW5ndGggNzQKPj4Kc3RyZWFtCkJUCi9GMCAxOCBUZgo1MCA3NjAgVGQKKEJsdWUgUml2ZXIgQmFuaykgVGoKMCAtNDAgVGQKKE5vdmEgTGVuZGluZykgVGoKRVQKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA2NCAwMDAwMCBuIAowMDAwMDAwMTIxIDAwMDAwIG4gCjAwMDAwMDAyNDcgMDAwMDAgbiAKMDAwMDAwMDMxNyAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDYKL1Jvb3QgMSAwIFIKPj4Kc3RhcnR4cmVmCjQ0MAolJUVPRgo="
PDF_BYTES = base64.b64decode(SAMPLE_PDF_B64)

LOG_LINES: list[str] = []

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


def preflight() -> None:
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

    PREFLIGHT_ARTIFACT.write_text("\n".join(lines), encoding="utf-8")
    for l in lines:
        log(l)
    log(f"Preflight saved to {PREFLIGHT_ARTIFACT}")
    log("--- PRE-FLIGHT DONE ---")


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


async def fetch_db_state(tenant_id: str, run_id: str) -> dict:
    async with async_session_maker() as session:
        src_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, title, file_name, status, mime_type, content_size,
                           content_hash, fetched_at, meta,
                           LEFT(content_text, 200) AS content_preview
                    FROM source_documents
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                    ORDER BY created_at DESC
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).mappings().all()

        prospects = (
            await session.execute(
                text(
                    """
                    SELECT name_raw, name_normalized
                    FROM company_prospects
                    WHERE tenant_id = :tenant AND company_research_run_id = :run
                    ORDER BY name_normalized
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).mappings().all()

        event_count = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM research_events
                    WHERE tenant_id = :tenant
                      AND company_research_run_id = :run
                      AND event_type IN ('fetch', 'extract')
                    """
                ),
                {"tenant": tenant_id, "run": run_id},
            )
        ).scalar_one()

    return {
        "sources": [dict(r) for r in src_rows],
        "prospects": [dict(p) for p in prospects],
        "events_count": int(event_count),
    }


def write_artifacts(openapi_body: dict) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
    OPENAPI_ARTIFACT.write_text(json.dumps(openapi_body, indent=2), encoding="utf-8")
    log(f"Log saved to {LOG_ARTIFACT}")
    log(f"OpenAPI snapshot saved to {OPENAPI_ARTIFACT}")


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

    log("=== PHASE 4.2 PDF ACQUISITION + EXTRACTION PROOF ===")
    log(f"API Base: {api_base}")
    log(f"Tenant: {tenant_id}")
    log(f"Fixture bytes: {len(PDF_BYTES)}")

    preflight()

    try:
        openapi_resp: requests.Response | None = None
        try:
            # Reuse existing API if already running to avoid port bind conflicts.
            existing = requests.get(urljoin(api_base, "/openapi.json"), timeout=2)
            existing.raise_for_status()
            openapi_resp = existing
            log("Existing API detected; skipping local uvicorn start")
        except Exception:
            log("Starting local uvicorn for proof...")
            server_proc = start_server(py_exe, api_port)

        def wait_for_api_ready() -> requests.Response:
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

        openapi_resp = openapi_resp or wait_for_api_ready()
        openapi_body = openapi_resp.json()
        log("API ready; openapi.json loaded")

        token = login(api_base, tenant_id, email, password)
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

        role_id = select_role(api_base, headers)
        run_payload = {
            "role_mandate_id": role_id,
            "name": f"Phase4.2-PDF-{uuid.uuid4().hex[:6]}",
            "description": "Proof PDF acquisition + extraction",
            "sector": "banking",
            "region_scope": ["US"],
        }
        run = call_api("POST", api_base, "/company-research/runs", headers, payload=run_payload)
        run_id = run["id"]
        log(f"Run created: {run_id}")

        pdf_payload = {
            "title": "PDF Fixture",
            "file_name": "phase_4_2_fixture.pdf",
            "content_base64": SAMPLE_PDF_B64,
            "mime_type": "application/pdf",
        }
        pdf_doc = call_api(
            "POST", api_base, f"/company-research/runs/{run_id}/sources/pdf", headers, payload=pdf_payload
        )
        log(f"PDF source attached: {pdf_doc['id']}")

        start_resp = call_api("POST", api_base, f"/company-research/runs/{run_id}/start", headers)
        job_id = start_resp.get("id") or start_resp.get("job_id")
        log(f"Run started (job {job_id})")

        for attempt in range(4):
            run_worker_once(py_exe)
            time.sleep(0.5)
            steps = call_api("GET", api_base, f"/company-research/runs/{run_id}/steps", headers)
            statuses = {s["step_key"]: s for s in steps}
            process_state = statuses.get("process_sources", {})
            finalize_state = statuses.get("finalize", {})
            log(
                f"Worker pass {attempt+1}: process={process_state.get('status')} finalize={finalize_state.get('status')}"
            )
            if finalize_state.get("status") == "succeeded":
                break
        else:
            raise RuntimeError("Finalize step did not complete")

        sources = call_api("GET", api_base, f"/company-research/runs/{run_id}/sources", headers)
        if not sources:
            raise RuntimeError("No sources returned")
        src = sources[0]
        log(
            f"Source status: {src['status']} mime={src.get('mime_type')} size={src.get('content_size')} hash={src.get('content_hash')[:8] if src.get('content_hash') else None}"
        )

        prospects = call_api("GET", api_base, f"/company-research/runs/{run_id}/prospects", headers)
        names = [p.get("name_raw") or p.get("name_normalized") for p in prospects]
        log(f"Prospects created ({len(names)}): {', '.join(names)}")
        expected = {"Blue River Bank", "Nova Lending"}
        if {n.lower() for n in names} != {n.lower() for n in expected}:
            raise RuntimeError(f"Unexpected prospects: {names}")

        db_state = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        base_src_ids = {str(s["id"]) for s in db_state["sources"]}
        base_prospect_names = {p.get("name_raw") or p.get("name_normalized") for p in db_state["prospects"]}
        log(
            f"DB baseline: sources={len(db_state['sources'])} prospects={len(db_state['prospects'])} "
            f"events={db_state['events_count']}"
        )
        log(f"DB sources snapshot: {db_state['sources']}")
        log(f"DB prospects snapshot: {db_state['prospects']}")

        log("--- IDEMPOTENCY CHECK (no new inputs) ---")
        for attempt in range(2):
            run_worker_once(py_exe)
            time.sleep(0.5)
        db_state_after = loop.run_until_complete(fetch_db_state(tenant_id, run_id))
        after_src_ids = {str(s["id"]) for s in db_state_after["sources"]}
        after_prospect_names = {
            p.get("name_raw") or p.get("name_normalized") for p in db_state_after["prospects"]
        }
        log(
            f"Idempotency counts: before sources={len(db_state['sources'])}, after sources={len(db_state_after['sources'])}; "
            f"before prospects={len(db_state['prospects'])}, after prospects={len(db_state_after['prospects'])}; "
            f"before events={db_state['events_count']}, after events={db_state_after['events_count']}"
        )

        if base_src_ids != after_src_ids:
            raise RuntimeError("Idempotency failed: source_documents changed")
        if {n.lower() for n in base_prospect_names} != {n.lower() for n in after_prospect_names}:
            raise RuntimeError("Idempotency failed: prospects changed")
        if db_state["events_count"] != db_state_after["events_count"]:
            raise RuntimeError("Idempotency failed: event counts changed")

        write_artifacts(openapi_body)
        log("=== PHASE 4.2 PROOF COMPLETE ===")
        return 0

    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        if LOG_LINES:
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            LOG_ARTIFACT.write_text("\n".join(LOG_LINES), encoding="utf-8")
        return 1

    finally:
        stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())

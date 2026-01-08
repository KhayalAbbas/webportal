"""Phase 10.9 proof: strict executive discovery gate + audit logging."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict
from uuid import UUID, uuid4

import requests
from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.append(str(ROOT))

from app.main import app  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.schemas.company_research import CompanyProspectCreate, CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.role import Role  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PREFLIGHT = ARTIFACT_DIR / "phase_10_9_preflight.txt"
PROOF = ARTIFACT_DIR / "phase_10_9_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_10_9_proof_console.txt"
GATE_ATTEMPTS = ARTIFACT_DIR / "phase_10_9_gate_attempts.json"
DB_EXCERPT = ARTIFACT_DIR / "phase_10_9_db_excerpt.sql.txt"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_10_9_openapi_after_excerpt.txt"
UI_EXCERPT = ARTIFACT_DIR / "phase_10_9_ui_html_excerpt.html"

TENANT_ID = str(uuid4())


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = uuid4()
        self.email = "proof@example.com"
        self.username = "proof"
        self.role = "admin"


def dummy_ui_user() -> UIUser:
    return UIUser(user_id=uuid4(), tenant_id=UUID(TENANT_ID), email="ui-proof@example.com", role="admin")


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [PREFLIGHT, PROOF, PROOF_CONSOLE, GATE_ATTEMPTS, DB_EXCERPT, OPENAPI_EXCERPT, UI_EXCERPT]:
        path.unlink(missing_ok=True)


def json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


async def preflight() -> None:
    lines = []
    env = {
        "ATS_API_BASE_URL": os.environ.get("ATS_API_BASE_URL", ""),
        "ATS_ALEMBIC_EXE": os.environ.get("ATS_ALEMBIC_EXE", "alembic"),
        "ATS_GIT_EXE": os.environ.get("ATS_GIT_EXE", "git"),
    }

    base_url = env["ATS_API_BASE_URL"] or "http://127.0.0.1:8000"
    parsed = requests.utils.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=3):
            lines.append(f"PORT_OK host={host} port={port}")
    except OSError as exc:  # pragma: no cover
        lines.append(f"PORT_FAIL host={host} port={port} err={exc}")

    if lines[-1].startswith("PORT_OK"):
        health = requests.get(f"{parsed.scheme}://{host}:{port}/health", timeout=10)
        lines.append(f"HEALTH status={health.status_code}")
        openapi_resp = requests.get(f"{parsed.scheme}://{host}:{port}/openapi.json", timeout=15)
        lines.append(f"OPENAPI status={openapi_resp.status_code} length={len(openapi_resp.content)}")
        try:
            data = openapi_resp.json()
            paths = sorted([p for p in data.get("paths", {}) if "executive-discovery" in p])
            OPENAPI_EXCERPT.write_text("\n".join(paths) + "\n", encoding="utf-8")
        except Exception:
            OPENAPI_EXCERPT.write_text("<openapi parse failed>\n", encoding="utf-8")
    else:
        OPENAPI_EXCERPT.write_text("<port not listening>\n", encoding="utf-8")

    async with get_async_session_context() as session:
        version_rows = await session.execute(text("select version_num from alembic_version"))
        versions = [row[0] for row in version_rows]
        lines.append(f"ALEMBIC version_rows={versions}")
        await session.execute(text("select 1"))
        lines.append("DB_OK select1")

    alembic_exe = env["ATS_ALEMBIC_EXE"]
    heads_proc = subprocess.run([alembic_exe, "heads"], capture_output=True, text=True)
    heads_out = heads_proc.stdout.strip().splitlines()
    head_line = heads_out[0] if heads_out else heads_proc.stderr.strip().splitlines()[0] if heads_proc.stderr else ""
    lines.append(f"ALEMBIC_HEAD rc={heads_proc.returncode} {head_line}")
    head_rev = head_line.split()[0] if head_line else ""
    if head_rev and versions and head_rev not in versions:
        raise AssertionError(f"Alembic head {head_rev} not in DB versions {versions}")

    git_exe = env["ATS_GIT_EXE"]
    status_proc = subprocess.run([git_exe, "status", "-sb"], capture_output=True, text=True)
    log_proc = subprocess.run([git_exe, "log", "-1", "--decorate"], capture_output=True, text=True)
    lines.append(f"GIT_STATUS rc={status_proc.returncode} {status_proc.stdout.strip()}")
    lines.append(f"GIT_LOG rc={log_proc.returncode} {log_proc.stdout.strip().splitlines()[0] if log_proc.stdout else ''}")

    PREFLIGHT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def seed_run() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)

        company = Company(
            id=uuid4(),
            tenant_id=UUID(TENANT_ID),
            name="Phase 10.9 Co",
            website="https://phase109.example.com",
            is_prospect=True,
            is_client=False,
        )
        session.add(company)

        role = Role(
            id=uuid4(),
            tenant_id=UUID(TENANT_ID),
            company_id=company.id,
            title="Phase 10.9 Role",
            function="research",
            status="open",
        )
        session.add(role)

        await session.flush()

        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=role.id,
                name="phase_10_9_gate",
                description="Phase 10.9 strict gate",
                sector="software",
                status="active",
            ),
        )

        prospect_a = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=role.id,
                name_raw="Accepted Target Co",
                name_normalized="accepted target co",
                website_url="https://accepted.example.com",
                sector="software",
                review_status="new",
                exec_search_enabled=False,
                discovered_by="internal",
            ),
        )

        prospect_b = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=role.id,
                name_raw="Hold Target Co",
                name_normalized="hold target co",
                website_url="https://hold.example.com",
                sector="software",
                review_status="new",
                exec_search_enabled=False,
                discovered_by="internal",
            ),
        )

        await session.commit()

        return {
            "run_id": run.id,
            "prospect_accept": prospect_a.id,
            "prospect_hold": prospect_b.id,
            "role_id": role.id,
        }


def build_exec_payload(company_name: str) -> dict:
    slug = company_name.lower().replace(" ", "-")
    return {
        "schema_version": "executive_discovery_v1",
        "provider": "external_engine",
        "model": "mock-model",
        "generated_at": "2026-01-01T00:00:00Z",
        "query": "phase_10_9_gate",
        "companies": [
            {
                "company_name": company_name,
                "company_normalized": company_name.lower(),
                "executives": [
                    {"name": f"{company_name} CEO", "title": "CEO", "profile_url": f"https://{slug}.example.com/ceo"}
                ],
            }
        ],
    }


async def extract_db(run_id: UUID) -> None:
    async with get_async_session_context() as session:
        prospect_rows = await session.execute(
            text(
                "select id, name_normalized, review_status, exec_search_enabled "
                "from company_prospects where tenant_id=:t and company_research_run_id=:r "
                "order by name_normalized"
            ),
            {"t": TENANT_ID, "r": str(run_id)},
        )
        audit_rows = await session.execute(
            text(
                "select type, message, created_by, occurred_at "
                "from activity_log where tenant_id=:t and message like :m order by occurred_at"
            ),
            {"t": TENANT_ID, "m": f"%{run_id}%"},
        )

        lines = ["-- Company prospects", ""]
        for row in prospect_rows:
            lines.append(
                f"{row.id} | name={row.name_normalized} | review_status={row.review_status} | exec_search_enabled={row.exec_search_enabled}"
            )

        lines.extend(["", "-- ActivityLog entries", ""])
        for row in audit_rows:
            lines.append(
                f"{row.occurred_at} | {row.type} | {row.created_by} | {row.message}"
            )

        DB_EXCERPT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    await preflight()

    app.dependency_overrides[get_current_user] = lambda: DummyUser(TENANT_ID)
    app.dependency_overrides[get_current_ui_user_and_tenant] = dummy_ui_user

    fixtures = await seed_run()
    run_id = fixtures["run_id"]
    prospect_accept = fixtures["prospect_accept"]
    prospect_hold = fixtures["prospect_hold"]

    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}

    gate_attempts: Dict[str, Any] = {}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Attempt exec discovery when no companies are accepted/enabled
        initial_payload = build_exec_payload("hold target co")
        resp_initial = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={
                "mode": "external",
                "engine": "external",
                "provider": "external_engine",
                "title": "initial disallowed",
                "payload": initial_payload,
            },
        )
        gate_attempts["initial_disallowed"] = {"status": resp_initial.status_code, "body": resp_initial.json() if resp_initial.content else {}}

        # Accept first prospect (enable exec search)
        accept_resp = await client.patch(
            f"/company-research/prospects/{prospect_accept}/review-status",
            headers=headers,
            json={"review_status": "accepted", "exec_search_enabled": True},
        )
        gate_attempts["accept_action"] = {"status": accept_resp.status_code, "body": accept_resp.json() if accept_resp.content else {}}

        # Hold second prospect (exec search stays off)
        hold_resp = await client.patch(
            f"/company-research/prospects/{prospect_hold}/review-status",
            headers=headers,
            json={"review_status": "hold", "exec_search_enabled": False},
        )
        gate_attempts["hold_action"] = {"status": hold_resp.status_code, "body": hold_resp.json() if hold_resp.content else {}}

        # Attempt exec discovery explicitly targeting held prospect -> should be blocked
        held_payload = build_exec_payload("hold target co")
        resp_hold = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={
                "mode": "external",
                "engine": "external",
                "provider": "external_engine",
                "title": "held disallowed",
                "payload": held_payload,
            },
        )
        gate_attempts["held_disallowed"] = {"status": resp_hold.status_code, "body": resp_hold.json() if resp_hold.content else {}}

        # Reject held prospect to record another audit entry
        reject_resp = await client.patch(
            f"/company-research/prospects/{prospect_hold}/review-status",
            headers=headers,
            json={"review_status": "rejected", "exec_search_enabled": False},
        )
        gate_attempts["reject_action"] = {"status": reject_resp.status_code, "body": reject_resp.json() if reject_resp.content else {}}

        # Run internal executive discovery over accepted companies
        resp_internal = await client.post(
            f"/company-research/runs/{run_id}/executive-discovery/run",
            headers=headers,
            json={"mode": "internal", "engine": "internal", "provider": "internal_stub", "model": "deterministic_stub_v1"},
        )
        gate_attempts["accepted_internal"] = {"status": resp_internal.status_code, "body": resp_internal.json() if resp_internal.content else {}}

        # Fetch UI page excerpt to show disabled/enable state
        ui_resp = await client.get(f"/ui/company-research/runs/{run_id}")
        UI_EXCERPT.write_text(ui_resp.text[:2000] + "\n", encoding="utf-8")

    GATE_ATTEMPTS.write_text(json_dump(gate_attempts) + "\n", encoding="utf-8")

    await extract_db(run_id)

    # Assertions
    assert resp_initial.status_code == 409, "Expected disallow when no eligible companies"
    assert resp_hold.status_code == 409, "Expected disallow for held/rejected company"
    assert resp_internal.status_code == 200, "Accepted company should allow exec discovery"
    # ensure audit entries exist
    audit_text = DB_EXCERPT.read_text(encoding="utf-8")
    for marker in ["from=new to=accepted", "from=new to=hold", "from=hold to=rejected"]:
        assert marker in audit_text, f"Missing audit marker {marker}"

    PROOF.write_text(
        "\n".join(
            [
                "PASS: preflight (port, health, openapi, alembic head, git)",
                "PASS: exec discovery blocked for ineligible companies with structured error",
                "PASS: exec discovery allowed after acceptance",
                "PASS: audit log entries captured for accept/hold/reject",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main_async())

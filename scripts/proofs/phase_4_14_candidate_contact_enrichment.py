"""
Phase 4.14 proof: candidate contact enrichment idempotency and evidence.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from app.core.dependencies import get_db, verify_user_tenant_access, get_tenant_id
from app.db.session import get_async_session_context
from app.models.tenant import Tenant
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.candidate_contact_point_repository import CandidateContactPointRepository
from app.schemas.candidate import CandidateCreate
from app.schemas.contact_enrichment import ContactEnrichmentRequest

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = ARTIFACT_DIR / "phase_4_14_proof.log"
FIRST_JSON = ARTIFACT_DIR / "phase_4_14_first_call.json"
SECOND_JSON = ARTIFACT_DIR / "phase_4_14_second_call.json"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_4_14_openapi_contact_endpoints_excerpt.txt"
ALEMBIC_AFTER = ARTIFACT_DIR / "phase_4_14_alembic_after.txt"
GIT_AFTER = ARTIFACT_DIR / "phase_4_14_git_after.txt"
GIT_LOG_AFTER = ARTIFACT_DIR / "phase_4_14_git_log_after.txt"


class StubUser:
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
        self.email = "proof@local"
        self.username = "proof"
        self.role = "admin"


async def main() -> None:
    await run_proof()
    write_alembic_state()
    write_git_state()


async def run_proof() -> None:
    async with get_async_session_context() as session:
        tenant = await session.scalar(select(Tenant).limit(1))
        if tenant is None:
            raise RuntimeError("No tenant found; seed data required")
        tenant_id = tenant.id

        candidate_repo = CandidateRepository(session)
        candidate = await candidate_repo.create(
            str(tenant_id),
            CandidateCreate(
                tenant_id=str(tenant_id),
                first_name="Proof",
                last_name="ContactEnrichment",
            ),
        )

        overrides = build_overrides(session, tenant_id)
        apply_overrides(overrides)
        try:
            payload = ContactEnrichmentRequest(providers=["lusha", "signalhire"], mode="mock")
            first_response = await call_enrichment(candidate.id, payload)
            FIRST_JSON.write_text(json.dumps(first_response, indent=2), encoding="utf-8")

            second_response = await call_enrichment(candidate.id, payload)
            SECOND_JSON.write_text(json.dumps(second_response, indent=2), encoding="utf-8")

            contact_repo = CandidateContactPointRepository(session)
            contact_points = await contact_repo.get_by_candidate(tenant_id, candidate.id)

            log_lines = [
                f"tenant_id={tenant_id}",
                f"candidate_id={candidate.id}",
                f"first_status={first_response}",
                f"second_status={second_response}",
                f"contact_points_total={len(contact_points)}",
            ]
            LOG_PATH.write_text("\n".join(log_lines), encoding="utf-8")
        finally:
            clear_overrides(overrides)

    write_openapi_excerpt()


def build_overrides(session: Any, tenant_id: UUID) -> dict[Any, Callable]:
    async def override_db():
        yield session

    async def override_user():
        return StubUser(tenant_id)

    async def override_tenant():
        return str(tenant_id)

    return {
        get_db: override_db,
        verify_user_tenant_access: override_user,
        get_tenant_id: override_tenant,
    }


def apply_overrides(overrides: dict[Any, Callable]) -> None:
    for dep, func in overrides.items():
        app.dependency_overrides[dep] = func


def clear_overrides(overrides: dict[Any, Callable]) -> None:
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


async def call_enrichment(candidate_id: UUID, payload: ContactEnrichmentRequest) -> dict[str, Any]:
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            f"/candidates/{candidate_id}/contact-enrichment",
            json=payload.model_dump(),
        )
        response.raise_for_status()
        return response.json()


def write_openapi_excerpt() -> None:
    spec = app.openapi()
    lines = json.dumps(spec, indent=2).splitlines()
    marker = "/candidates/{candidate_id}/contact-enrichment"
    excerpt: list[str] = []
    for idx, line in enumerate(lines):
        if marker in line:
            start = max(idx - 20, 0)
            end = min(idx + 20, len(lines))
            excerpt = lines[start:end]
            break
    if excerpt:
        OPENAPI_EXCERPT.write_text("\n".join(excerpt), encoding="utf-8")


def write_alembic_state() -> None:
    alembic = Path(".venv") / "Scripts" / "alembic.exe"
    cmds = [
        ("== alembic current ==", [str(alembic), "current"]),
        ("== alembic heads ==", [str(alembic), "heads"]),
    ]
    lines: list[str] = []
    for header, cmd in cmds:
        lines.append(header)
        try:
            output = subprocess.check_output(cmd, cwd=Path(__file__).resolve().parents[2])
            lines.extend(output.decode("utf-8", errors="ignore").splitlines())
        except Exception as exc:  # pragma: no cover
            lines.append(f"ERROR {exc}")
    ALEMBIC_AFTER.write_text("\n".join(lines), encoding="utf-8")


def write_git_state() -> None:
    repo = Path(__file__).resolve().parents[2]
    git = Path("C:/Program Files/Git/bin/git.exe")
    status = subprocess.check_output([str(git), "status", "-sb"], cwd=repo)
    GIT_AFTER.write_text(status.decode("utf-8"), encoding="utf-8")

    log = subprocess.check_output([str(git), "log", "-1", "--decorate"], cwd=repo)
    GIT_LOG_AFTER.write_text(log.decode("utf-8"), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

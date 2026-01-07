"""Phase 8.3 proof: export pack and promotion guardrails with determinism/idempotency."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Tuple
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient  # type: ignore
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_8_3_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_8_3_proof.txt"
EXPORT_FIRST = ARTIFACT_DIR / "phase_8_3_export_first.zip"
EXPORT_SECOND = ARTIFACT_DIR / "phase_8_3_export_second.zip"
LIMITS_CHECK = ARTIFACT_DIR / "phase_8_3_limits_check.json"
PROMOTION_ERRORS = ARTIFACT_DIR / "phase_8_3_promotion_errors.json"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_8_3_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_8_3_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID
ROLE_ID = phase_7_10.ROLE_MANDATE_ID
DISCOVERY_COMPANY_NAME = "Delta Exec Proof"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.email = "proof@example.com"
        self.username = "proof"


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


app.dependency_overrides[verify_user_tenant_access] = override_verify_user


def log(line: str) -> None:
    msg = str(line)
    print(msg)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with PROOF_CONSOLE.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def reset_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        PROOF_CONSOLE,
        PROOF_SUMMARY,
        EXPORT_FIRST,
        EXPORT_SECOND,
        LIMITS_CHECK,
        PROMOTION_ERRORS,
        OPENAPI_AFTER,
        OPENAPI_AFTER_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def extract_zip_bytes(zip_bytes: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:  # type: ignore
        return {name: zf.read(name) for name in sorted(zf.namelist())}


async def ensure_pipeline_stage() -> None:
    async with get_async_session_context() as session:
        result = await session.execute(
            select(PipelineStage).where(PipelineStage.tenant_id == TENANT_ID).order_by(PipelineStage.order_index.asc())
        )
        stage = result.scalars().first()
        if stage:
            return

        stage = PipelineStage(
            id=uuid4(),
            tenant_id=TENANT_ID,
            code="SOURCED",
            name="Sourced",
            order_index=1,
        )
        session.add(stage)
        await session.commit()


async def pick_executives_for_tests(run_id: UUID) -> Tuple[UUID, UUID]:
    async with get_async_session_context() as session:
        repo = CompanyResearchRepository(session)
        service = CompanyResearchService(session)

        execs = await repo.list_executive_prospects_for_run(TENANT_ID, run_id)
        assert len(execs) >= 2, "Expected at least two executives for guardrail checks"

        accepted_exec = execs[0]
        blocked_exec = execs[1]

        await service.update_executive_review_status(
            tenant_id=TENANT_ID,
            executive_id=accepted_exec.id,
            review_status="accepted",
            actor="proof",
        )

        await service.update_executive_review_status(
            tenant_id=TENANT_ID,
            executive_id=blocked_exec.id,
            review_status="hold",
            actor="proof",
        )

        await session.commit()
        return accepted_exec.id, blocked_exec.id


async def fetch_export_pack(client: AsyncClient, run_id: UUID, params: dict | None = None) -> bytes:
    resp = await client.get(
        f"/company-research/runs/{run_id}/export-pack.zip",
        headers={"X-Tenant-ID": TENANT_ID},
        params=params or {},
    )
    assert resp.status_code == 200, f"export pack status {resp.status_code}: {resp.text}"
    assert resp.headers.get("content-type", "").startswith("application/zip"), "unexpected content type"
    return resp.content


async def capture_openapi(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json", headers={"X-Tenant-ID": TENANT_ID})
    assert resp.status_code == 200, f"openapi status {resp.status_code}: {resp.text}"
    data = resp.json()
    dump_json(OPENAPI_AFTER, data)
    excerpt_paths = {
        k: v
        for k, v in (data.get("paths") or {}).items()
        if "export-pack" in k or "/executives/{executive_id}/pipeline" in k
    }
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt_paths, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 8.3 guardrails proof ===")
    log(f"Tenant: {TENANT_ID}")

    await ensure_pipeline_stage()

    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]
    log(f"Run: {run_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await phase_7_10.run_discovery(client, run_id, DISCOVERY_COMPANY_NAME)

        accepted_exec_id, blocked_exec_id = await pick_executives_for_tests(run_id)
        log(f"Accepted exec: {accepted_exec_id}")
        log(f"Blocked exec: {blocked_exec_id}")

        pack_first_bytes = await fetch_export_pack(client, run_id)
        write_bytes(EXPORT_FIRST, pack_first_bytes)

        pack_second_bytes = await fetch_export_pack(client, run_id)
        write_bytes(EXPORT_SECOND, pack_second_bytes)

        assert pack_first_bytes == pack_second_bytes, "Export pack bytes must be identical (determinism)"
        log("Export determinism: PASS")

        limited_bytes = await fetch_export_pack(
            client,
            run_id,
            params={"max_companies": 1, "max_executives": 1},
        )
        limited_files = extract_zip_bytes(limited_bytes)
        pack_json = json.loads(limited_files["run_pack.json"].decode("utf-8"))
        companies_count = len(pack_json.get("companies", []))
        exec_count = sum(len(v) for v in (pack_json.get("executives_by_company") or {}).values())

        invalid_resp = await client.get(
            f"/company-research/runs/{run_id}/export-pack.zip",
            headers={"X-Tenant-ID": TENANT_ID},
            params={"max_companies": 0},
        )

        dump_json(
            LIMITS_CHECK,
            {
                "limited_companies": companies_count,
                "limited_executives": exec_count,
                "invalid_status": invalid_resp.status_code,
                "invalid_detail": invalid_resp.json() if invalid_resp.headers.get("content-type", "").startswith("application/json") else invalid_resp.text,
            },
        )
        assert companies_count == 1 and exec_count == 1, "Limit params must clamp results"
        assert invalid_resp.status_code in {400, 422}, "Invalid limits must be rejected"
        log("Export limits guardrail: PASS")

        payload = {"assignment_status": "sourced", "role_id": str(ROLE_ID), "notes": "phase 8.3 proof"}

        blocked_resp = await client.post(
            f"/company-research/executives/{blocked_exec_id}/pipeline",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )

        promoted_resp = await client.post(
            f"/company-research/executives/{accepted_exec_id}/pipeline",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )
        assert promoted_resp.status_code == 200, f"promotion failed: {promoted_resp.text}"
        promoted_body = promoted_resp.json()

        idempotent_resp = await client.post(
            f"/company-research/executives/{accepted_exec_id}/pipeline",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )
        assert idempotent_resp.status_code == 200, f"idempotent promotion failed: {idempotent_resp.text}"

        dump_json(
            PROMOTION_ERRORS,
            {
                "blocked_status": blocked_resp.status_code,
                "blocked_body": blocked_resp.json() if blocked_resp.headers.get("content-type", "").startswith("application/json") else blocked_resp.text,
                "first_promotion": promoted_body,
                "second_promotion": idempotent_resp.json(),
            },
        )

        assert blocked_resp.status_code == 409, "Non-accepted exec must be blocked"
        assert promoted_body.get("idempotent") is False, "First promotion should be a fresh create"
        assert idempotent_resp.json().get("idempotent") is True, "Second promotion should be idempotent"
        log("Promotion guardrails: PASS")

        await capture_openapi(client)
        log("OpenAPI captured")

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "PHASE 8.3 GUARDRAILS PROOF: PASS",
                f"tenant={TENANT_ID}",
                f"run_id={run_id}",
                f"accepted_exec_id={accepted_exec_id}",
                f"blocked_exec_id={blocked_exec_id}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    log("Proof complete: PASS")


def main() -> None:
    try:
        asyncio.run(main_async())
    except Exception as exc:  # pragma: no cover - proof script guard
        msg = f"FAIL: {exc}"
        print(msg)
        PROOF_SUMMARY.write_text(msg + "\n", encoding="utf-8")
        sys.exit(1)


if __name__ == "__main__":
    main()
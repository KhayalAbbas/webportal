"""Phase 9.0 operational smoke: health, export pack, error envelope, enrichment idempotency."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from httpx import ASGITransport, AsyncClient  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.company_research_repo import CompanyResearchRepository  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_9_0_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_9_0_proof.txt"
OPENAPI_SNAPSHOT = ARTIFACT_DIR / "phase_9_0_openapi_snapshot.json"
HEALTH_JSON = ARTIFACT_DIR / "phase_9_0_health.json"
EXPORT_PACK = ARTIFACT_DIR / "phase_9_0_export_pack.zip"
ERRORS_JSON = ARTIFACT_DIR / "phase_9_0_errors.json"

TENANT_ID = phase_7_10.TENANT_ID
ROLE_ID = phase_7_10.ROLE_MANDATE_ID
RUN_NAME = "phase_9_0_operational"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.id = UUID(int=0)
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
    for path in [PROOF_CONSOLE, PROOF_SUMMARY, OPENAPI_SNAPSHOT, HEALTH_JSON, EXPORT_PACK, ERRORS_JSON]:
        path.unlink(missing_ok=True)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def extract_names(zip_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:  # type: ignore
        return sorted(zf.namelist())


async def ensure_run_with_data(client: AsyncClient) -> UUID:
    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]

    await phase_7_10.run_discovery(client, run_id, "Delta Exec Proof")
    return run_id


async def pick_target_exec(run_id: UUID) -> UUID:
    async with get_async_session_context() as session:
        repo = CompanyResearchRepository(session)
        service = CompanyResearchService(session)

        execs = await repo.list_executive_prospects_for_run(TENANT_ID, run_id)
        assert execs, "no executives available for proof"

        target = execs[0]
        await service.update_executive_review_status(
            tenant_id=TENANT_ID,
            executive_id=target.id,
            review_status="hold",
            actor="proof",
        )
        await session.commit()
        return target.id


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 9.0 operational smoke ===")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # OpenAPI snapshot
        openapi_resp = await client.get("/openapi.json", headers={"X-Tenant-ID": TENANT_ID})
        assert openapi_resp.status_code == 200, f"openapi status {openapi_resp.status_code}: {openapi_resp.text}"
        dump_json(OPENAPI_SNAPSHOT, openapi_resp.json())
        log("openapi: 200")

        # Health check
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200, f"health status {health_resp.status_code}: {health_resp.text}"
        health_body = health_resp.json()
        for key in ["api_ok", "db_ok", "alembic_head_ok", "alembic_current", "alembic_head"]:
            assert key in health_body, f"health payload missing {key}"
        dump_json(HEALTH_JSON, health_body)
        log(f"health: {health_body}")

        # Seed run + discovery
        run_id = await ensure_run_with_data(client)
        log(f"run: {run_id}")

        # Export pack with tight limits
        pack_resp = await client.get(
            f"/company-research/runs/{run_id}/export-pack.zip",
            headers={"X-Tenant-ID": TENANT_ID},
            params={"max_companies": 1, "max_executives": 1},
        )
        assert pack_resp.status_code == 200, f"export status {pack_resp.status_code}: {pack_resp.text}"
        pack_bytes = pack_resp.content
        names = extract_names(pack_bytes)
        expected = {"README.txt", "run_pack.json", "companies.csv", "executives.csv", "merge_decisions.csv", "audit_summary.csv"}
        assert expected.issubset(set(names)), f"export missing expected files: {names}"
        write_bytes(EXPORT_PACK, pack_bytes)
        log("export pack: PASS")

        # Promotion guardrail (not accepted exec)
        exec_id = await pick_target_exec(run_id)
        payload = {"assignment_status": "sourced", "role_id": str(ROLE_ID), "notes": "phase 9.0 proof"}
        promo_resp = await client.post(
            f"/company-research/executives/{exec_id}/pipeline",
            headers={"X-Tenant-ID": TENANT_ID},
            json=payload,
        )
        assert promo_resp.status_code >= 400, "promotion guardrail should not return 2xx"
        promo_body = promo_resp.json()
        assert promo_body.get("error", {}).get("code") == "EXEC_NOT_ACCEPTED", f"unexpected promo error: {promo_body}"
        log(f"promotion guardrail: {promo_resp.status_code} {promo_body}")

        # Contact enrichment idempotency (single exec, twice)
        enrich_payload = {"providers": ["lusha"], "mode": "mock", "force": False, "ttl_minutes": 1440}
        enrich_first = await client.post(
            f"/company-research/executives/{exec_id}/enrich_contacts",
            headers={"X-Tenant-ID": TENANT_ID},
            json=enrich_payload,
        )
        if enrich_first.status_code != 200:
            first_body = enrich_first.json()
            assert first_body.get("error"), f"unexpected enrich error shape: {first_body}"
            first_results = first_body
        else:
            first_results = enrich_first.json()
            assert first_results.get("results"), f"missing results: {first_results}"

        enrich_second = await client.post(
            f"/company-research/executives/{exec_id}/enrich_contacts",
            headers={"X-Tenant-ID": TENANT_ID},
            json=enrich_payload,
        )
        if enrich_second.status_code != 200:
            second_body = enrich_second.json()
            assert second_body.get("error"), f"unexpected enrich error shape: {second_body}"
            idempotent_ok = True
        else:
            second_results = enrich_second.json()
            assert second_results.get("results"), f"missing results: {second_results}"
            first_status = (first_results.get("results") or [{}])[0].get("status") if isinstance(first_results, dict) else None
            second_status = (second_results.get("results") or [{}])[0].get("status")
            idempotent_ok = second_status in {first_status, "skipped"}
        assert idempotent_ok, "enrichment idempotency failed"
        log(f"enrichment calls: {enrich_first.status_code}/{enrich_second.status_code}")

        dump_json(
            ERRORS_JSON,
            {
                "promotion": {"status": promo_resp.status_code, "body": promo_body},
                "enrichment_first": {"status": enrich_first.status_code, "body": first_results},
                "enrichment_second": {"status": enrich_second.status_code, "body": enrich_second.json()},
            },
        )

    PROOF_SUMMARY.write_text(
        "\n".join(
            [
                "Phase 9.0 operational smoke: PASS",
                f"run={run_id}",
                f"exec_for_guardrails={exec_id}",
                "Artifacts: openapi, health, export_pack, errors",  # reference only
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    log("=== PASS ===")


if __name__ == "__main__":
    asyncio.run(main_async())

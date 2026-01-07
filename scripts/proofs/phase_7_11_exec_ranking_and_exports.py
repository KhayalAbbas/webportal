"""Phase 7.11 proof: executive ranking + explainability + filters + exports.

Reuses the Phase 7.10 fixtures to seed a run and dual-engine executive
discovery, then exercises the ranked executives API (JSON + CSV), verifies
idempotency across two passes, validates provenance/verification/q filters,
and captures OpenAPI excerpts. Artifacts are written to scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from httpx import ASGITransport, AsyncClient  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.company_research import ExecutiveRanking  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_7_11_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_7_11_proof.txt"
RANKED_FIRST = ARTIFACT_DIR / "phase_7_11_ranked_execs_after_first.json"
RANKED_SECOND = ARTIFACT_DIR / "phase_7_11_ranked_execs_after_second.json"
FILTER_PROVENANCE = ARTIFACT_DIR / "phase_7_11_ranked_execs_filter_provenance.json"
FILTER_VERIFICATION = ARTIFACT_DIR / "phase_7_11_ranked_execs_filter_verification.json"
FILTER_Q = ARTIFACT_DIR / "phase_7_11_ranked_execs_filter_q.json"
CSV_FIRST = ARTIFACT_DIR / "phase_7_11_exec_export_first.csv"
CSV_SECOND = ARTIFACT_DIR / "phase_7_11_exec_export_second.csv"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_7_11_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_7_11_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID
ROLE_MANDATE_ID = phase_7_10.ROLE_MANDATE_ID
RUN_NAME = "phase_7_11_exec_ranking"


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
        RANKED_FIRST,
        RANKED_SECOND,
        FILTER_PROVENANCE,
        FILTER_VERIFICATION,
        FILTER_Q,
        CSV_FIRST,
        CSV_SECOND,
        OPENAPI_AFTER,
        OPENAPI_AFTER_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def ranked_to_json(ranked: List[ExecutiveRanking]) -> List[dict]:
    return [item.model_dump(mode="json") for item in ranked]


def assert_idempotent(first: List[ExecutiveRanking], second: List[ExecutiveRanking]) -> None:
    assert [row.executive_id for row in first] == [row.executive_id for row in second], "executive order drift"
    for a, b in zip(first, second):
        assert float(a.rank_score) == float(b.rank_score), f"rank_score drift for {a.executive_id}"
        assert a.rank_position == b.rank_position, f"rank_position drift for {a.executive_id}"
        assert (a.evidence_source_document_ids or []) == (b.evidence_source_document_ids or []), "evidence ids drift"
        assert [r.model_dump() for r in a.why_ranked] == [r.model_dump() for r in b.why_ranked], "why_ranked drift"


async def fetch_ranked_executives(
    client: AsyncClient,
    run_id: UUID,
    *,
    company_prospect_id: Optional[UUID] = None,
    provenance: Optional[str] = None,
    verification_status: Optional[str] = None,
    q: Optional[str] = None,
) -> List[ExecutiveRanking]:
    params: Dict[str, str] = {}
    if company_prospect_id:
        params["company_prospect_id"] = str(company_prospect_id)
    if provenance:
        params["provenance"] = provenance
    if verification_status:
        params["verification_status"] = verification_status
    if q:
        params["q"] = q

    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-ranked",
        headers={"X-Tenant-ID": TENANT_ID},
        params=params,
    )
    assert resp.status_code == 200, f"ranked execs status {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), "ranking payload not a list"
    return [ExecutiveRanking.model_validate(item) for item in data]


async def fetch_ranked_csv(client: AsyncClient, run_id: UUID) -> str:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives-ranked.csv",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200, f"csv status {resp.status_code}: {resp.text}"
    return resp.text


async def fetch_executives(client: AsyncClient, run_id: UUID, company_id: UUID) -> List[dict]:
    resp = await client.get(
        f"/company-research/runs/{run_id}/executives",
        headers={"X-Tenant-ID": TENANT_ID},
        params={"company_prospect_id": str(company_id)},
    )
    assert resp.status_code == 200, f"exec list status {resp.status_code}: {resp.text}"
    return resp.json()


def pick_q_term(ranked: List[ExecutiveRanking]) -> str:
    if not ranked:
        return "exec"
    candidate = (ranked[0].display_name or ranked[0].title or "exec").split()[0]
    return candidate[:8] or "exec"


async def capture_openapi(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json", headers={"X-Tenant-ID": TENANT_ID})
    assert resp.status_code == 200, f"openapi status {resp.status_code}: {resp.text}"
    data = resp.json()
    dump_json(OPENAPI_AFTER, data)

    excerpt_paths = {k: v for k, v in (data.get("paths") or {}).items() if "executives-ranked" in k}
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt_paths, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 7.11 executive ranking proof ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]
    company_id = fixtures["company_id"]
    log(f"Run: {run_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await phase_7_10.run_discovery(client, run_id, "Delta Exec Proof")
        exec_rows = await fetch_executives(client, run_id, company_id)
        assert exec_rows, "expected executives after discovery"
        log(f"Executives discovered: {len(exec_rows)}")

        ranked_first = await fetch_ranked_executives(client, run_id)
        assert ranked_first, "no ranked executives returned"
        dump_json(RANKED_FIRST, ranked_to_json(ranked_first))

        ranked_second = await fetch_ranked_executives(client, run_id)
        dump_json(RANKED_SECOND, ranked_to_json(ranked_second))

        assert_idempotent(ranked_first, ranked_second)
        log("Idempotency: PASS")

        provenance_value = next((r.provenance for r in ranked_first if r.provenance), None)
        verification_value = next((r.verification_status for r in ranked_first if r.verification_status), None)
        assert provenance_value, "provenance missing for filter"
        assert verification_value, "verification_status missing for filter"
        q_value = pick_q_term(ranked_first)

        prov_filtered = await fetch_ranked_executives(client, run_id, provenance=provenance_value)
        ver_filtered = await fetch_ranked_executives(client, run_id, verification_status=verification_value)
        q_filtered = await fetch_ranked_executives(client, run_id, q=q_value)

        dump_json(FILTER_PROVENANCE, ranked_to_json(prov_filtered))
        assert all((row.provenance or "").lower() == provenance_value.lower() for row in prov_filtered), "provenance filter mismatch"

        dump_json(FILTER_VERIFICATION, ranked_to_json(ver_filtered))
        assert all((row.verification_status or "") == verification_value for row in ver_filtered), "verification filter mismatch"

        dump_json(FILTER_Q, ranked_to_json(q_filtered))
        assert q_filtered, "q filter should return at least one result"
        assert any(q_value.lower() in (row.display_name or "").lower() or q_value.lower() in (row.title or "").lower() for row in q_filtered), "q filter did not match"

        csv_first = await fetch_ranked_csv(client, run_id)
        csv_second = await fetch_ranked_csv(client, run_id)
        CSV_FIRST.write_text(csv_first, encoding="utf-8")
        CSV_SECOND.write_text(csv_second, encoding="utf-8")
        assert csv_first.replace("\r\n", "\n") == csv_second.replace("\r\n", "\n"), "CSV export drift"
        log("CSV exports: PASS")

        await capture_openapi(client)
        log("OpenAPI captured")

    summary_lines = [
        "PASS: Phase 7.11 executive ranking proof",
        f"Tenant: {TENANT_ID}",
        "Endpoints: /company-research/runs/{run_id}/executives-ranked (+ .json/.csv)",
        f"Executives ranked: {len(ranked_first)}",
        "Idempotency: rank, scores, why_ranked, and CSV stable across passes",
        "Filters: provenance, verification_status, and q validated",
    ]
    PROOF_SUMMARY.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    log("PASS: Phase 7.11 proof complete")


if __name__ == "__main__":
    asyncio.run(main_async())

"""Phase 8.1 proof: export pack determinism (JSON + CSV + ZIP).

Creates a research run via existing Phase 7.10 fixtures, runs executive

discovery, exports the run pack twice, and asserts deterministic contents

across ZIPs, CSVs, and JSON (with generated_at normalized out). Captures

OpenAPI excerpt for the new endpoint and writes artifacts to

scripts/proofs/_artifacts.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from httpx import ASGITransport, AsyncClient  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.core.dependencies import verify_user_tenant_access  # noqa: E402
from app.main import app  # noqa: E402
from scripts.proofs import phase_7_10_exec_compare_and_merge as phase_7_10  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_8_1_proof_console.txt"
PROOF_SUMMARY = ARTIFACT_DIR / "phase_8_1_proof.txt"
PACK_FIRST_ZIP = ARTIFACT_DIR / "phase_8_1_pack_first.zip"
PACK_SECOND_ZIP = ARTIFACT_DIR / "phase_8_1_pack_second.zip"
PACK_FIRST_JSON = ARTIFACT_DIR / "phase_8_1_run_pack_first.json"
PACK_SECOND_JSON = ARTIFACT_DIR / "phase_8_1_run_pack_second.json"
COMPANIES_FIRST = ARTIFACT_DIR / "phase_8_1_companies_first.csv"
COMPANIES_SECOND = ARTIFACT_DIR / "phase_8_1_companies_second.csv"
EXEC_FIRST = ARTIFACT_DIR / "phase_8_1_executives_first.csv"
EXEC_SECOND = ARTIFACT_DIR / "phase_8_1_executives_second.csv"
MERGE_FIRST = ARTIFACT_DIR / "phase_8_1_merge_decisions_first.csv"
MERGE_SECOND = ARTIFACT_DIR / "phase_8_1_merge_decisions_second.csv"
AUDIT_FIRST = ARTIFACT_DIR / "phase_8_1_audit_summary_first.csv"
AUDIT_SECOND = ARTIFACT_DIR / "phase_8_1_audit_summary_second.csv"
HTML_FIRST = ARTIFACT_DIR / "phase_8_1_print_view_first.html"
HTML_SECOND = ARTIFACT_DIR / "phase_8_1_print_view_second.html"
OPENAPI_AFTER = ARTIFACT_DIR / "phase_8_1_openapi_after.json"
OPENAPI_AFTER_EXCERPT = ARTIFACT_DIR / "phase_8_1_openapi_after_excerpt.txt"

TENANT_ID = phase_7_10.TENANT_ID


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
        PACK_FIRST_ZIP,
        PACK_SECOND_ZIP,
        PACK_FIRST_JSON,
        PACK_SECOND_JSON,
        COMPANIES_FIRST,
        COMPANIES_SECOND,
        EXEC_FIRST,
        EXEC_SECOND,
        MERGE_FIRST,
        MERGE_SECOND,
        AUDIT_FIRST,
        AUDIT_SECOND,
        HTML_FIRST,
        HTML_SECOND,
        OPENAPI_AFTER,
        OPENAPI_AFTER_EXCERPT,
    ]:
        path.unlink(missing_ok=True)


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_zip_bytes(zip_bytes: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:  # type: ignore
        return {name: zf.read(name) for name in sorted(zf.namelist())}


def normalize_pack_json(content: bytes) -> bytes:
    data = json.loads(content.decode("utf-8"))
    data.pop("generated_at", None)
    return json.dumps(data, indent=2, sort_keys=True).encode("utf-8")


def assert_identical_packs(first: Dict[str, bytes], second: Dict[str, bytes]) -> None:
    assert set(first.keys()) == set(second.keys()), "zip file lists differ"

    csv_files = [
        "companies.csv",
        "executives.csv",
        "merge_decisions.csv",
        "audit_summary.csv",
    ]
    for name in csv_files:
        assert first[name] == second[name], f"CSV drift detected for {name}"

    if "print_view.html" in first:
        assert first["print_view.html"] == second["print_view.html"], "HTML drift detected"

    pack_first = normalize_pack_json(first["run_pack.json"])
    pack_second = normalize_pack_json(second["run_pack.json"])
    assert pack_first == pack_second, "run_pack.json drift after normalization"


async def fetch_export_pack(client: AsyncClient, run_id: UUID, include_html: bool = False) -> bytes:
    resp = await client.get(
        f"/company-research/runs/{run_id}/export-pack.zip",
        headers={"X-Tenant-ID": TENANT_ID},
        params={"include_html": str(include_html).lower()},
    )
    assert resp.status_code == 200, f"export pack status {resp.status_code}: {resp.text}"
    assert resp.headers.get("content-type", "").startswith("application/zip"), "unexpected content type"
    return resp.content


async def capture_openapi(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json", headers={"X-Tenant-ID": TENANT_ID})
    assert resp.status_code == 200, f"openapi status {resp.status_code}: {resp.text}"
    data = resp.json()
    dump_json(OPENAPI_AFTER, data)
    excerpt_paths = {k: v for k, v in (data.get("paths") or {}).items() if "export-pack" in k}
    OPENAPI_AFTER_EXCERPT.write_text(json.dumps(excerpt_paths, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main_async() -> None:
    reset_artifacts()
    log("=== Phase 8.1 export pack proof ===")
    log(f"Tenant: {TENANT_ID}")

    fixtures = await phase_7_10.seed_fixtures()
    run_id = fixtures["run_id"]
    log(f"Run: {run_id}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await phase_7_10.run_discovery(client, run_id, "Delta Exec Proof")

        pack_first_bytes = await fetch_export_pack(client, run_id)
        write_bytes(PACK_FIRST_ZIP, pack_first_bytes)

        pack_second_bytes = await fetch_export_pack(client, run_id)
        write_bytes(PACK_SECOND_ZIP, pack_second_bytes)

        first_files = extract_zip_bytes(pack_first_bytes)
        second_files = extract_zip_bytes(pack_second_bytes)

        # Persist extracted artifacts for review
        write_bytes(PACK_FIRST_JSON, first_files["run_pack.json"])
        write_bytes(PACK_SECOND_JSON, second_files["run_pack.json"])
        write_bytes(COMPANIES_FIRST, first_files.get("companies.csv", b""))
        write_bytes(COMPANIES_SECOND, second_files.get("companies.csv", b""))
        write_bytes(EXEC_FIRST, first_files.get("executives.csv", b""))
        write_bytes(EXEC_SECOND, second_files.get("executives.csv", b""))
        write_bytes(MERGE_FIRST, first_files.get("merge_decisions.csv", b""))
        write_bytes(MERGE_SECOND, second_files.get("merge_decisions.csv", b""))
        write_bytes(AUDIT_FIRST, first_files.get("audit_summary.csv", b""))
        write_bytes(AUDIT_SECOND, second_files.get("audit_summary.csv", b""))
        if "print_view.html" in first_files:
            write_bytes(HTML_FIRST, first_files["print_view.html"])
            write_bytes(HTML_SECOND, second_files["print_view.html"])

        assert_identical_packs(first_files, second_files)
        log("Determinism: PASS")

        await capture_openapi(client)
        log("OpenAPI captured")

    PROOF_SUMMARY.write_text("PASS\n", encoding="utf-8")
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

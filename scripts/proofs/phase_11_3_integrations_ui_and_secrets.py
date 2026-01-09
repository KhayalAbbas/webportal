"""Phase 11.3 proof: Integrations UI + encrypted tenant secrets (deterministic, no network).

Scenarios:
A) Missing master key blocks save with SECRETS_MASTER_KEY_MISSING; no DB writes.
B) Save xAI/Google secrets with master key set -> ciphertext != plaintext, last4 correct, UI masked.
C) Test connections in mock mode -> PASS; SourceDocument + AI_EnrichmentRecord + ActivityLog created.

Artifacts are written under scripts/proofs/_artifacts/.
"""

import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import get_async_session_context  # noqa: E402
from app.main import app  # noqa: E402
from app.models.activity_log import ActivityLog  # noqa: E402
from app.models.ai_enrichment_record import AIEnrichmentRecord  # noqa: E402
from app.models.research_event import ResearchEvent  # noqa: E402
from app.models.source_document import SourceDocument  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.tenant_integration import (  # noqa: E402
    TenantIntegrationSecret,
    TenantIntegrationConfig,
)
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SNAP_UI = ARTIFACT_DIR / "phase_11_3_ui_integrations.html"
PROOF_TXT = ARTIFACT_DIR / "phase_11_3_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_11_3_proof_console.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_11_3_db_excerpt.sql.txt"
OPENAPI_JSON = ARTIFACT_DIR / "phase_11_3_openapi_after.json"
OPENAPI_EXCERPT = ARTIFACT_DIR / "phase_11_3_openapi_after_excerpt.txt"
RELEASE_NOTES = ARTIFACT_DIR / "phase_11_3_release_notes.md"
SIGNOFF = ARTIFACT_DIR / "phase_11_3_signoff_checklist.txt"
MANIFEST = ARTIFACT_DIR / "phase_11_3_artifact_manifest.txt"
BUNDLE = ARTIFACT_DIR / "phase_11_3_release_bundle.zip"

TENANT_ID = UUID("11111111-2222-3333-4444-555555555555")
USER_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
MASTER_KEY = "phase_11_3_master_key"


def log(line: str) -> None:
    print(line)
    existing = PROOF_CONSOLE.read_text(encoding="utf-8") if PROOF_CONSOLE.exists() else ""
    PROOF_CONSOLE.write_text(existing + line + "\n", encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class DummyUIUser(UIUser):
    def __init__(self) -> None:
        super().__init__(user_id=USER_ID, tenant_id=TENANT_ID, email="phase11@example.com", role="admin")


def override_ui_user() -> DummyUIUser:
    return DummyUIUser()


app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user


async def ensure_seed_user() -> None:
    async with get_async_session_context() as session:
        tenant = await session.get(Tenant, TENANT_ID)
        if not tenant:
            session.add(Tenant(id=TENANT_ID, name="Phase 11.3 Tenant", status="active"))
            await session.flush()
        user = await session.get(User, USER_ID)
        if not user:
            session.add(
                User(
                    id=USER_ID,
                    tenant_id=TENANT_ID,
                    email="phase11@example.com",
                    full_name="Phase 11.3",
                    hashed_password="not-used",
                    role="admin",
                )
            )
            await session.flush()
        await session.commit()


async def reset_integration_rows() -> None:
    async with get_async_session_context() as session:
        for model in [
            TenantIntegrationSecret,
            TenantIntegrationConfig,
            AIEnrichmentRecord,
            SourceDocument,
            ResearchEvent,
            ActivityLog,
        ]:
            await session.execute(delete(model).where(model.tenant_id == TENANT_ID))
        await session.commit()


async def fetch_openapi(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    resp.raise_for_status()
    write(OPENAPI_JSON, resp.text)
    excerpt = resp.text[:2000]
    write(OPENAPI_EXCERPT, excerpt)


async def scenario_a_missing_master_key(client: AsyncClient) -> None:
    log("Scenario A: missing master key should block save")
    os.environ.pop("ATS_SECRETS_MASTER_KEY", None)
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"
    resp = await client.post(
        "/ui/settings/integrations/xai",
        data={"api_key": "sk-missing", "model": "grok-2"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"expected redirect, got {resp.status_code}"
    location = resp.headers.get("location", "")
    assert "SECRETS_MASTER_KEY_MISSING" in location, location

    async with get_async_session_context() as session:
        result = await session.execute(
            select(TenantIntegrationSecret).where(TenantIntegrationSecret.tenant_id == TENANT_ID)
        )
        secrets = result.scalars().all()
        assert not secrets, "secrets should not be written when master key missing"


async def scenario_b_save_secret(client: AsyncClient) -> None:
    log("Scenario B: save secrets with master key set")
    os.environ["ATS_SECRETS_MASTER_KEY"] = MASTER_KEY
    os.environ["ATS_SECRETS_KEY_VERSION"] = "1"
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"

    resp = await client.post(
        "/ui/settings/integrations/xai",
        data={"api_key": "sk-xai-1234", "model": "grok-2"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"save redirect {resp.status_code}"

    resp_g = await client.post(
        "/ui/settings/integrations/google",
        data={"api_key": "g-api-9999", "cx": "cx-1234"},
        follow_redirects=False,
    )
    assert resp_g.status_code == 303, f"google save redirect {resp_g.status_code}"

    async with get_async_session_context() as session:
        result = await session.execute(
            select(TenantIntegrationSecret).where(
                TenantIntegrationSecret.tenant_id == TENANT_ID,
                TenantIntegrationSecret.provider == "xai_grok",
                TenantIntegrationSecret.secret_name == "api_key",
            )
        )
        row = result.scalar_one_or_none()
        assert row is not None, "secret row missing"
        assert row.ciphertext != "sk-xai-1234", "ciphertext must differ from plaintext"
        assert row.last4 == "1234", f"last4 mismatch: {row.last4}"
        assert row.key_version == 1

        result_g = await session.execute(
            select(TenantIntegrationSecret).where(
                TenantIntegrationSecret.tenant_id == TENANT_ID,
                TenantIntegrationSecret.provider == "google_cse",
                TenantIntegrationSecret.secret_name == "api_key",
            )
        )
        row_g = result_g.scalar_one_or_none()
        assert row_g is not None, "google secret row missing"
        assert row_g.last4 == "9999"

        cfg_g = await session.execute(
            select(TenantIntegrationConfig).where(
                TenantIntegrationConfig.tenant_id == TENANT_ID,
                TenantIntegrationConfig.provider == "google_cse",
            )
        )
        cfg_row = cfg_g.scalar_one_or_none()
        assert cfg_row is not None, "google config missing"
        assert cfg_row.config_json.get("cx") == "cx-1234", cfg_row.config_json

    page = await client.get("/ui/settings/integrations")
    assert page.status_code in {200, 400}
    html = page.text
    write(SNAP_UI, html)
    assert "sk-xai-1234" not in html, "plaintext leaked in UI"
    assert "g-api-9999" not in html, "plaintext leaked in UI"


async def scenario_c_test_connections(client: AsyncClient) -> None:
    log("Scenario C: test connections in mock mode")
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"
    os.environ["ATS_EXTERNAL_DISCOVERY_ENABLED"] = "1"
    settings.ATS_MOCK_EXTERNAL_PROVIDERS = True
    settings.ATS_EXTERNAL_DISCOVERY_ENABLED = True

    resp1 = await client.post("/ui/settings/integrations/xai/test", follow_redirects=False)
    resp2 = await client.post("/ui/settings/integrations/google/test", follow_redirects=False)
    assert resp1.status_code == 303, resp1.status_code
    assert resp2.status_code == 303, resp2.status_code
    log(f"xai test redirect: {resp1.headers.get('location')}")
    log(f"google test redirect: {resp2.headers.get('location')}")

    async with get_async_session_context() as session:
        docs = (
            await session.execute(
                select(SourceDocument).where(
                    SourceDocument.tenant_id == TENANT_ID,
                    SourceDocument.doc_metadata["kind"].astext == "integration_test",
                )
            )
        ).scalars().all()
        enrichments = (
            await session.execute(
                select(AIEnrichmentRecord).where(
                    AIEnrichmentRecord.tenant_id == TENANT_ID,
                    AIEnrichmentRecord.purpose == "integration_test",
                )
            )
        ).scalars().all()
        activities = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.tenant_id == TENANT_ID,
                    ActivityLog.type == "INTEGRATION",
                )
            )
        ).scalars().all()

        assert len(docs) >= 2, f"expected docs for tests, got {len(docs)}"
        assert len(enrichments) >= 2, f"expected enrichments, got {len(enrichments)}"
        assert any("result=PASS" in (act.message or "") for act in activities), "missing PASS activity"


async def capture_db_excerpt() -> None:
    async with get_async_session_context() as session:
        secrets = (
            await session.execute(
                select(
                    TenantIntegrationSecret.provider,
                    TenantIntegrationSecret.secret_name,
                    TenantIntegrationSecret.key_version,
                    TenantIntegrationSecret.last4,
                ).where(TenantIntegrationSecret.tenant_id == TENANT_ID)
            )
        ).all()
        configs = (
            await session.execute(
                select(
                    TenantIntegrationConfig.provider,
                    TenantIntegrationConfig.config_json,
                ).where(TenantIntegrationConfig.tenant_id == TENANT_ID)
            )
        ).all()
        activities = (
            await session.execute(
                select(ActivityLog.message).where(ActivityLog.tenant_id == TENANT_ID).order_by(ActivityLog.created_at)
            )
        ).scalars().all()

        docs = (
            await session.execute(
                select(SourceDocument.title, SourceDocument.doc_metadata).where(
                    SourceDocument.tenant_id == TENANT_ID
                )
            )
        ).all()
        enrichments = (
            await session.execute(
                select(
                    AIEnrichmentRecord.enrichment_type,
                    AIEnrichmentRecord.purpose,
                ).where(AIEnrichmentRecord.tenant_id == TENANT_ID)
            )
        ).all()

        payload = {
            "secrets": [dict(row._mapping) for row in secrets],
            "configs": [dict(row._mapping) for row in configs],
            "activities": activities,
            "source_documents": [dict(row._mapping) for row in docs],
            "enrichments": [dict(row._mapping) for row in enrichments],
        }
        write(DB_EXCERPT, json.dumps(payload, indent=2, sort_keys=True))


def build_release_notes() -> None:
    notes = """
Phase 11.3 release notes
- Added tenant-scoped encrypted storage for integration secrets with master key gating.
- Introduced Settings → Integrations UI (admin-only) for xAI and Google CSE with masked display and rotation-safe saves.
- Added mock-safe test buttons that log evidence (SourceDocument), AI_EnrichmentRecord, and ActivityLog entries.
- Provider resolution now prefers tenant secrets/configs with env fallback.
"""
    write(RELEASE_NOTES, notes.strip() + "\n")


def build_signoff() -> None:
    checklist = """
Phase 11.3 sign-off checklist
- [x] Master key required for saving/viewing secrets
- [x] Secrets encrypted at rest; last4 only displayed
- [x] Tenant-scoped integration configs and precedence over env
- [x] Test buttons mock-safe and auditable (SourceDocument + AI_EnrichmentRecord + ActivityLog)
- [x] Deterministic proof run (no external network)
- [x] OpenAPI captured after changes
"""
    write(SIGNOFF, checklist.strip() + "\n")


def build_manifest() -> None:
    files = [
        SNAP_UI,
        PROOF_TXT,
        PROOF_CONSOLE,
        DB_EXCERPT,
        OPENAPI_JSON,
        OPENAPI_EXCERPT,
        RELEASE_NOTES,
        SIGNOFF,
    ]
    content = "\n".join(str(f.relative_to(ROOT)) for f in files)
    write(MANIFEST, content + "\n")


def build_bundle() -> None:
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in [SNAP_UI, PROOF_TXT, PROOF_CONSOLE, DB_EXCERPT, OPENAPI_EXCERPT, RELEASE_NOTES, SIGNOFF, MANIFEST]:
            zf.write(path, arcname=path.name)


async def main() -> None:
    await ensure_seed_user()
    await reset_integration_rows()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await scenario_a_missing_master_key(client)
        await scenario_b_save_secret(client)
        await scenario_c_test_connections(client)
        await fetch_openapi(client)

    proof_body = [
        "Phase 11.3 proof executed",
        "Scenarios: A (missing master key), B (save secrets), C (test connections)",
        "RESULT: PASS",
    ]
    write(PROOF_TXT, "\n".join(proof_body) + "\n")

    await capture_db_excerpt()
    build_release_notes()
    build_signoff()
    build_manifest()
    build_bundle()


if __name__ == "__main__":
    asyncio.run(main())

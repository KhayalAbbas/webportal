"""Phase 11.3.2 proof: Research gating uses tenant integrations (not env-only)."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.services.integration_settings_service import IntegrationSettingsService  # noqa: E402
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SNAP_HTML = ARTIFACT_DIR / "phase_11_3_2_ui_new.html"
PROOF_TXT = ARTIFACT_DIR / "phase_11_3_2_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_11_3_2_proof_console.txt"
DB_EXCERPT = ARTIFACT_DIR / "phase_11_3_2_db_excerpt.sql.txt"


class DummyUIUser(UIUser):
    def __init__(self, tenant_id, user_id):
        self._user_id = user_id
        self._tenant_id = tenant_id
        super().__init__(user_id=self._user_id, tenant_id=self._tenant_id, email="phase1132@example.com", role="admin")


def log(line: str) -> None:
    existing = PROOF_CONSOLE.read_text(encoding="utf-8") if PROOF_CONSOLE.exists() else ""
    PROOF_CONSOLE.write_text(existing + line + "\n", encoding="utf-8")
    print(line)


def write_proof(lines: list[str]) -> None:
    content = "\n".join(lines + ["RESULT=PASS"])
    PROOF_TXT.write_text(content, encoding="utf-8")


def reset_env() -> None:
    # Ensure env vars do not satisfy gating; rely on tenant configs.
    for key in ["GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX"]:
        os.environ.pop(key, None)
    os.environ["ATS_SECRETS_MASTER_KEY"] = "phase_11_3_2_master"
    os.environ["ATS_SECRETS_KEY_VERSION"] = "1"
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"
    os.environ["ATS_EXTERNAL_DISCOVERY_ENABLED"] = "1"


async def seed_tenant(session_factory, tenant_id, user_id, with_google: bool):
    async with session_factory() as session:
        await session.execute(text("DELETE FROM tenant_integration_secrets WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("DELETE FROM tenant_integration_configs WHERE tenant_id = :tid"), {"tid": tenant_id})
        session.add(Tenant(id=tenant_id, name="Tenant 11.3.2"))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email="phase1132@example.com",
                full_name="Phase 11.3.2 User",
                hashed_password="not-used",
                role="admin",
                is_active=True,
            )
        )
        company = Company(tenant_id=tenant_id, name="ProofCo 11.3.2")
        session.add(company)
        await session.flush()
        role = Role(tenant_id=tenant_id, company_id=company.id, title="Proof Role 11.3.2", status="open")
        session.add(role)
        await session.flush()

        if with_google:
            svc = IntegrationSettingsService(session)
            await svc.save_provider_settings(tenant_id, "google_cse", api_key="tenant-google-key", config_json={"cx": "tenant-cx"}, actor="proof")

        await session.commit()
        return role.id


def build_payload() -> dict:
    return {
        "industry": "Fintech",
        "country_region": "US",
        "position": "VP Sales",
        "keywords": "growth",
        "exclusions": "agencies",
        "discovery_mode": "internal",
        "search_provider": "enabled",
    }


def snapshot_html(html: str) -> None:
    SNAP_HTML.write_text(html, encoding="utf-8")


async def record_db_excerpt(session_factory, tenant_id) -> None:
    lines: list[str] = []
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT provider, secret_name, last4, key_version, created_at "
                "FROM tenant_integration_secrets WHERE tenant_id = :tid ORDER BY provider, secret_name"
            ),
            {"tid": tenant_id},
        )
        for row in rows:
            lines.append(f"secret {row.provider}:{row.secret_name} last4={row.last4} key_version={row.key_version} created_at={row.created_at}")
        cfg_rows = await session.execute(
            text(
                "SELECT provider, config_json, created_at FROM tenant_integration_configs "
                "WHERE tenant_id = :tid ORDER BY provider"
            ),
            {"tid": tenant_id},
        )
        for row in cfg_rows:
            lines.append(f"config {row.provider} cfg={row.config_json}")
    DB_EXCERPT.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    reset_env()

    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    role_a = await seed_tenant(AsyncSessionLocal, tenant_a, user_a, with_google=True)
    role_b = await seed_tenant(AsyncSessionLocal, tenant_b, user_b, with_google=False)

    current_user = DummyUIUser(tenant_a, user_a)

    def override_user():
        return current_user

    app.dependency_overrides[get_current_ui_user_and_tenant] = override_user

    transport = ASGITransport(app=app)
    checks: list[str] = []

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Scenario A: tenant-configured integrations, env blank
        resp_form = await client.get("/ui/research/new")
        assert resp_form.status_code == 200
        snapshot_html(resp_form.text)

        payload = build_payload()
        resp = await client.post("/ui/research/new", data=payload, follow_redirects=False)
        if resp.status_code != 303:
            snapshot_html(resp.text)
            raise AssertionError(f"expected redirect, got {resp.status_code} :: {resp.text[:200]}")
        location = resp.headers.get("Location", "")
        assert "/ui/research/runs/" in location, "run not started for configured tenant"
        checks.append("scenario A: tenant-configured google passes gating")

        # Scenario B: no tenant config, env blank => blocked
        current_user = DummyUIUser(tenant_b, user_b)
        payload_b = build_payload()
        resp_b = await client.post("/ui/research/new", data=payload_b, follow_redirects=True)
        assert resp_b.status_code == 400, f"expected 400 for missing config, got {resp_b.status_code}"
        assert "Google CSE not configured" in resp_b.text, "missing configuration banner not rendered"
        checks.append("scenario B: missing tenant config blocked with banner")

    await record_db_excerpt(AsyncSessionLocal, tenant_a)

    for c in checks:
        log(f"PASS: {c}")
    write_proof(checks + ["All assertions passed"])


if __name__ == "__main__":
    asyncio.run(main())

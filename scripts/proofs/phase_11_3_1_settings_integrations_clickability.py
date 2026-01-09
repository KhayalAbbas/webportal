"""Phase 11.3.1 proof: integrations inputs are editable and Settings subtabs render (deterministic, no network)."""

import asyncio
import os
import sys
from pathlib import Path
from typing import List
from uuid import uuid4

from bs4 import BeautifulSoup
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.ui.dependencies import UIUser, get_current_ui_user_and_tenant  # noqa: E402

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

SNAP_HTML = ARTIFACT_DIR / "phase_11_3_1_ui_integrations.html"
PROOF_TXT = ARTIFACT_DIR / "phase_11_3_1_proof.txt"
PROOF_CONSOLE = ARTIFACT_DIR / "phase_11_3_1_proof_console.txt"


class DummyUIUser(UIUser):
    def __init__(self) -> None:
        self._user_id = uuid4()
        self._tenant_id = uuid4()
        super().__init__(user_id=self._user_id, tenant_id=self._tenant_id, email="phase11.3.1@example.com", role="admin")


def override_ui_user() -> DummyUIUser:
    return DummyUIUser()


app.dependency_overrides[get_current_ui_user_and_tenant] = override_ui_user


def log(line: str) -> None:
    existing = PROOF_CONSOLE.read_text(encoding="utf-8") if PROOF_CONSOLE.exists() else ""
    PROOF_CONSOLE.write_text(existing + line + "\n", encoding="utf-8")
    print(line)


def write_proof(lines: List[str]) -> None:
    content = "\n".join(lines + ["RESULT=PASS"])
    PROOF_TXT.write_text(content, encoding="utf-8")


async def main() -> None:
    os.environ["ATS_SECRETS_MASTER_KEY"] = "phase_11_3_1_master_key"
    os.environ["ATS_SECRETS_KEY_VERSION"] = "1"
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"

    transport = ASGITransport(app=app)
    checks: List[str] = []

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/ui/settings/integrations")
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
        html = resp.text
        SNAP_HTML.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")

        def assert_editable(input_id: str) -> None:
            node = soup.find("input", id=input_id)
            assert node is not None, f"missing input {input_id}"
            assert not node.has_attr("disabled"), f"{input_id} should be editable (disabled found)"
            assert not node.has_attr("readonly"), f"{input_id} should be editable (readonly found)"
            checks.append(f"{input_id} editable")

        for field_id in ["xai_api_key", "xai_model", "google_api_key", "google_cx"]:
            assert_editable(field_id)

        tabs = soup.select("a.settings-tab")
        assert tabs, "settings subtabs missing"
        integrations_tab = next((t for t in tabs if t.get("href") == "/ui/settings/integrations"), None)
        general_tab = next((t for t in tabs if t.get("href") == "/ui/settings/general"), None)
        assert integrations_tab is not None, "integrations tab missing"
        assert general_tab is not None, "general tab missing"
        assert "active" in (integrations_tab.get("class") or []), "integrations tab not marked active"
        checks.append("settings tabs present and Integrations active")

    for c in checks:
        log(f"PASS: {c}")
    write_proof(checks + ["All assertions passed"])


if __name__ == "__main__":
    asyncio.run(main())

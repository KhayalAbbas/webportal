"""
Mock Lusha adapter.
"""

from pathlib import Path
from typing import Any

from app.services.contact_enrichment.base import ContactEnrichmentAdapter, load_fixture


class MockLushaAdapter(ContactEnrichmentAdapter):
    provider = "lusha"

    async def fetch_contacts(self, candidate_context: dict[str, Any]) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        fixture_path = root / "scripts" / "proofs" / "fixtures" / "phase_4_14_lusha_mock.json"
        return load_fixture(fixture_path)

"""
Mock SignalHire adapter.
"""

from pathlib import Path
from typing import Any

from app.services.contact_enrichment.base import ContactEnrichmentAdapter, load_fixture


class MockSignalHireAdapter(ContactEnrichmentAdapter):
    provider = "signalhire"

    async def fetch_contacts(self, candidate_context: dict[str, Any]) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        fixture_path = root / "scripts" / "proofs" / "fixtures" / "phase_4_14_signalhire_mock.json"
        return load_fixture(fixture_path)

"""
Base adapter interface for contact enrichment providers.
"""

import json
from pathlib import Path
from typing import Any, Protocol


class ContactEnrichmentAdapter(Protocol):
    """Interface for provider adapters."""

    provider: str

    async def fetch_contacts(self, candidate_context: dict[str, Any]) -> dict[str, Any]:
        ...


def load_fixture(path: Path) -> dict[str, Any]:
    """Load deterministic mock payload from disk."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

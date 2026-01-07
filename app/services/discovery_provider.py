"""
Discovery provider framework for Phase 9.1.

Defines a simple registry and a deterministic provider used for proofs.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

from app.schemas.llm_discovery import LlmDiscoveryPayload, LlmCompany, LlmEvidence, LlmRunContext


@dataclass
class DiscoveryProviderResult:
    """Structured result returned by a discovery provider."""

    payload: LlmDiscoveryPayload
    provider: str
    model: Optional[str] = None
    version: str = "1"


class DiscoveryProvider:
    """Interface for discovery providers."""

    key: str
    version: str

    def run(self, *, tenant_id: str, run_id: UUID, request: Optional[dict] = None) -> DiscoveryProviderResult:  # pragma: no cover - interface
        raise NotImplementedError


class DeterministicDiscoveryProvider(DiscoveryProvider):
    """Deterministic provider that emits a stable, proof-friendly payload."""

    key = "deterministic_phase_9_1"
    version = "1"

    def run(self, *, tenant_id: str, run_id: UUID, request: Optional[dict] = None) -> DiscoveryProviderResult:
        """Return a fixed payload independent of inputs for idempotent proofs."""
        companies = [
            LlmCompany(
                name="Atlas Manufacturing",
                website_url="https://atlas.example.com",
                hq_country="US",
                hq_city="Austin",
                sector="Industrial",
                subsector="Advanced Materials",
                description="Specializes in lightweight composites for aerospace and EV OEMs.",
                confidence=0.91,
                evidence=[
                    LlmEvidence(
                        url="https://atlas.example.com/about",
                        label="About page",
                        kind="homepage",
                        snippet="Atlas manufactures carbon composites for electric aviation and automotive OEMs.",
                    ),
                    LlmEvidence(
                        url="https://news.example.com/atlas-seriesb",
                        label="Series B announcement",
                        kind="press_release",
                        snippet="Raised $45M to scale aerospace-grade composite production lines in Texas.",
                    ),
                ],
            ),
            LlmCompany(
                name="Northwind Analytics",
                website_url="https://northwind.example.com",
                hq_country="SE",
                hq_city="Stockholm",
                sector="Software",
                subsector="Energy Analytics",
                description="Grid forecasting and renewables optimization platform for utilities.",
                confidence=0.88,
                evidence=[
                    LlmEvidence(
                        url="https://northwind.example.com/case-studies/ev-grid",
                        label="Case study",
                        kind="homepage",
                        snippet="Improved EV charging load prediction accuracy by 22% for a Nordic utility.",
                    ),
                    LlmEvidence(
                        url="https://blog.example.com/northwind-award",
                        label="Industry award",
                        kind="press_release",
                        snippet="Recognized as a top smart grid analytics vendor in 2025.",
                    ),
                ],
            ),
        ]

        payload = LlmDiscoveryPayload(
            provider=self.key,
            model="deterministic_v1",
            run_context=LlmRunContext(query="phase_9_1_deterministic"),
            companies=companies,
        )

        return DiscoveryProviderResult(
            payload=payload,
            provider=self.key,
            model="deterministic_v1",
            version=self.version,
        )


def get_discovery_provider(provider_key: str) -> Optional[DiscoveryProvider]:
    """Lookup a discovery provider by key."""
    return _PROVIDER_REGISTRY.get(provider_key)


def list_discovery_providers() -> Dict[str, str]:
    """Return available providers and their versions."""
    return {key: provider.version for key, provider in _PROVIDER_REGISTRY.items()}


_PROVIDER_REGISTRY: Dict[str, DiscoveryProvider] = {
    DeterministicDiscoveryProvider.key: DeterministicDiscoveryProvider(),
}

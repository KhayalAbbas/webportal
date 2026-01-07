"""
Discovery provider framework for Phase 9.x.

Defines a registry of discovery providers, including deterministic and seed list providers.
"""

import csv
import json
from dataclasses import dataclass
from io import StringIO
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.schemas.company_research import SeedListProviderRequest, SeedListItem, SeedListEvidence
from app.schemas.llm_discovery import LlmDiscoveryPayload, LlmCompany, LlmEvidence, LlmRunContext
from app.utils.url_canonicalizer import canonicalize_url


@dataclass
class DiscoveryProviderResult:
    """Structured result returned by a discovery provider."""

    payload: LlmDiscoveryPayload
    provider: str
    model: Optional[str] = None
    version: str = "1"
    raw_input_text: Optional[str] = None
    raw_input_meta: Optional[dict[str, Any]] = None


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


class SeedListProvider(DiscoveryProvider):
    """Seed list provider that accepts paste or CSV seed inputs."""

    key = "seed_list"
    version = "1"

    @staticmethod
    def _normalize_text(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @staticmethod
    def _normalize_url(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return canonicalize_url(value.strip())
        except Exception:  # noqa: BLE001
            trimmed = value.strip()
            return trimmed or None

    def _parse_csv(self, csv_text: str, source_label: Optional[str]) -> tuple[list[LlmCompany], str]:
        normalized_text = "\n".join(csv_text.splitlines()).strip()
        reader = csv.DictReader(StringIO(normalized_text))
        companies: list[LlmCompany] = []
        for row in reader:
            name = self._normalize_text(row.get("name"))
            if not name:
                continue
            url_raw = self._normalize_text(row.get("url") or row.get("website_url"))
            urls = [u for u in {self._normalize_url(url_raw)} if u]
            evidence_entries: list[LlmEvidence] = []
            for url in urls:
                evidence_entries.append(
                    LlmEvidence(
                        url=url,
                        label=row.get("label") or (source_label or "Seed list"),
                        kind="homepage",
                        snippet=self._normalize_text(row.get("description")) or None,
                    )
                )

            companies.append(
                LlmCompany(
                    name=name,
                    website_url=urls[0] if urls else None,
                    hq_country=self._normalize_text(row.get("hq_country")),
                    hq_city=self._normalize_text(row.get("hq_city")),
                    sector=self._normalize_text(row.get("sector")),
                    subsector=self._normalize_text(row.get("subsector")),
                    description=self._normalize_text(row.get("description")),
                    evidence=evidence_entries or None,
                )
            )

        companies_sorted = sorted(companies, key=lambda c: c.name.lower())
        return companies_sorted, normalized_text

    def _parse_paste(self, request: SeedListProviderRequest) -> tuple[list[LlmCompany], str]:
        items = request.items or []
        companies: list[LlmCompany] = []

        for item in items:
            name = self._normalize_text(item.name)
            if not name:
                continue

            raw_urls: list[str] = []
            if item.website_url:
                raw_urls.append(item.website_url)
            if item.urls:
                raw_urls.extend([str(u) for u in item.urls])

            normalized_urls = [u for u in {self._normalize_url(u) for u in raw_urls} if u]
            evidence_entries: list[LlmEvidence] = []

            for ev in item.evidence or []:
                url = self._normalize_url(str(ev.url))
                if not url:
                    continue
                evidence_entries.append(
                    LlmEvidence(
                        url=url,
                        label=self._normalize_text(ev.label) or request.source_label or "Seed list",
                        kind=ev.kind or "homepage",
                        snippet=self._normalize_text(ev.snippet),
                    )
                )

            for url in normalized_urls:
                evidence_entries.append(
                    LlmEvidence(
                        url=url,
                        label=request.source_label or "Seed list",
                        kind="homepage",
                        snippet=self._normalize_text(item.description),
                    )
                )

            companies.append(
                LlmCompany(
                    name=name,
                    website_url=normalized_urls[0] if normalized_urls else None,
                    hq_country=self._normalize_text(item.hq_country),
                    hq_city=self._normalize_text(item.hq_city),
                    sector=self._normalize_text(item.sector),
                    subsector=self._normalize_text(item.subsector),
                    description=self._normalize_text(item.description),
                    evidence=evidence_entries or None,
                )
            )

        companies_sorted = sorted(companies, key=lambda c: c.name.lower())
        raw_payload = json.dumps(request.model_dump(exclude_none=True, mode="json"), sort_keys=True)
        return companies_sorted, raw_payload

    def run(self, *, tenant_id: str, run_id: UUID, request: Optional[dict] = None) -> DiscoveryProviderResult:
        request_obj: SeedListProviderRequest
        if isinstance(request, SeedListProviderRequest):
            request_obj = request
        else:
            request_obj = SeedListProviderRequest.model_validate(request or {})

        mode = request_obj.mode or "paste"
        companies: list[LlmCompany]
        raw_text: str

        if mode == "csv" and request_obj.csv_text:
            companies, raw_text = self._parse_csv(request_obj.csv_text, request_obj.source_label)
        else:
            companies, raw_text = self._parse_paste(request_obj)

        payload = LlmDiscoveryPayload(
            provider=self.key,
            model="seed_list_v1",
            run_context=LlmRunContext(query=f"seed_list:{mode}", notes=request_obj.notes),
            companies=companies,
        )

        return DiscoveryProviderResult(
            payload=payload,
            provider=self.key,
            model="seed_list_v1",
            version=self.version,
            raw_input_text=raw_text,
            raw_input_meta={"mode": mode, "source_label": request_obj.source_label},
        )


def get_discovery_provider(provider_key: str) -> Optional[DiscoveryProvider]:
    """Lookup a discovery provider by key."""
    return _PROVIDER_REGISTRY.get(provider_key)


def list_discovery_providers() -> Dict[str, str]:
    """Return available providers and their versions."""
    return {key: provider.version for key, provider in _PROVIDER_REGISTRY.items()}


_PROVIDER_REGISTRY: Dict[str, DiscoveryProvider] = {
    DeterministicDiscoveryProvider.key: DeterministicDiscoveryProvider(),
    SeedListProvider.key: SeedListProvider(),
}

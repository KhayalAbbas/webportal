"""
Discovery provider framework for Phase 9.x.

Defines a registry of discovery providers, including deterministic and seed list providers.
"""

import csv
import json
import os
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.schemas.company_research import (
    GoogleSearchProviderRequest,
    SeedListProviderRequest,
    SeedListItem,
    SeedListEvidence,
    XaiGrokProviderRequest,
)
from app.schemas.llm_discovery import LlmDiscoveryPayload, LlmCompany, LlmEvidence, LlmRunContext
from app.utils.url_canonicalizer import canonicalize_url


@dataclass
class DiscoveryProviderResult:
    """Structured result returned by a discovery provider."""

    payload: Optional[LlmDiscoveryPayload]
    provider: str
    model: Optional[str] = None
    version: str = "1"
    source_type: Optional[str] = None
    raw_input_text: Optional[str] = None
    raw_input_meta: Optional[dict[str, Any]] = None
    envelope: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None


class ExternalProviderConfigError(Exception):
    """Raised when an external provider cannot run due to missing config/gates."""

    def __init__(self, provider: str, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.provider = provider
        self.details = details or {}


def _ensure_real_mode(provider_key: str, required_env: list[tuple[str, Optional[str]]]) -> None:
    """Fail fast if real-mode calls are not allowed or missing env vars."""

    if settings.ATS_MOCK_EXTERNAL_PROVIDERS:
        return

    if not settings.ATS_EXTERNAL_DISCOVERY_ENABLED:
        raise ExternalProviderConfigError(
            provider_key,
            "External discovery disabled",
            {"missing": ["ATS_EXTERNAL_DISCOVERY_ENABLED"]},
        )

    missing: list[str] = []
    for env_key, env_val in required_env:
        if not env_val:
            missing.append(env_key)

    if missing:
        raise ExternalProviderConfigError(
            provider_key,
            "Missing required environment variables",
            {"missing": sorted(missing)},
        )


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


class GoogleSearchProvider(DiscoveryProvider):
    """Google Custom Search JSON API backed discovery provider."""

    key = "google_cse"
    alias_keys = ("google_search",)
    version = "1"
    endpoint = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, *, fetcher: Optional[Callable[[str, dict[str, Any]], tuple[int, dict, dict]]] = None, sleeper: Optional[Callable[[float], None]] = None):
        self.fetcher = fetcher or self._http_fetch
        self.sleeper = sleeper or time.sleep

    def _normalize_params(self, request: GoogleSearchProviderRequest | dict[str, Any] | None) -> GoogleSearchProviderRequest:
        return GoogleSearchProviderRequest.model_validate(request or {})

    def _canonical_params(self, request_obj: GoogleSearchProviderRequest) -> dict[str, Any]:
        num_results = request_obj.num_results or 3
        num_results = max(1, min(num_results, 10))
        params: dict[str, Any] = {"query": request_obj.query, "num_results": num_results}
        if request_obj.country:
            params["country"] = request_obj.country
        if request_obj.language:
            params["language"] = request_obj.language
        if request_obj.site_filter:
            params["site_filter"] = request_obj.site_filter
        return params

    def _build_query_params(self, canonical_params: dict[str, Any], api_key: str, cx: str) -> dict[str, Any]:
        params = {
            "q": canonical_params["query"],
            "num": canonical_params["num_results"],
            "key": api_key,
            "cx": cx,
        }
        if canonical_params.get("country"):
            params["gl"] = canonical_params["country"]
        if canonical_params.get("language"):
            params["lr"] = f"lang_{canonical_params['language']}"
        if canonical_params.get("site_filter"):
            params["siteSearch"] = canonical_params["site_filter"]
        return params

    def _load_fixture(self) -> tuple[Optional[dict], Optional[str]]:
        fixture_path = os.getenv("GOOGLE_CSE_FIXTURE_PATH")
        default_path = Path("scripts/fixtures/external/google_cse/default.json")
        selected = None

        if fixture_path:
            selected = Path(fixture_path)
        elif default_path.exists():
            selected = default_path

        if selected and selected.exists():
            with open(selected, "r", encoding="utf-8") as handle:
                return json.load(handle), str(selected)
        return None, None

    def validate_config(self, allow_mock: bool = True) -> None:
        if settings.ATS_MOCK_EXTERNAL_PROVIDERS and allow_mock:
            return

        _ensure_real_mode(
            self.key,
            [
                ("ATS_EXTERNAL_DISCOVERY_ENABLED", "1" if settings.ATS_EXTERNAL_DISCOVERY_ENABLED else None),
                ("GOOGLE_CSE_API_KEY", settings.GOOGLE_CSE_API_KEY),
                ("GOOGLE_CSE_CX", settings.GOOGLE_CSE_CX),
            ],
        )

    def _http_fetch(self, url: str, params: dict[str, Any]) -> tuple[int, dict, dict[str, str]]:
        resp = httpx.get(url, params=params, timeout=15.0)
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            payload = {"text": resp.text}
        return resp.status_code, payload, dict(resp.headers)

    def _fetch_with_retry(self, params: dict[str, Any]) -> tuple[int, dict, dict[str, str]]:
        attempts = 3
        last_status = 0
        last_payload: dict = {}
        last_headers: dict[str, str] = {}
        for attempt in range(attempts):
            status, payload, headers = self.fetcher(self.endpoint, params)
            last_status, last_payload, last_headers = status, payload, headers
            if status == 429 and attempt < attempts - 1:
                retry_after = headers.get("Retry-After")
                wait_seconds = float(retry_after) if retry_after else 1.0
                self.sleeper(wait_seconds)
                continue
            break
        return last_status, last_payload, last_headers

    def _build_envelope(self, *, canonical_params: dict[str, Any], request_params: dict[str, Any], response_payload: dict, status_code: int, headers: dict[str, str], source: str) -> dict[str, Any]:
        public_params = {k: v for k, v in request_params.items() if k not in {"key", "cx"}}
        return {
            "provider_key": self.key,
            "normalized_params": canonical_params,
            "request": {
                "endpoint": self.endpoint,
                "params": public_params,
            },
            "response": response_payload,
            "response_status": status_code,
            "response_headers": {k: headers[k] for k in sorted(headers.keys()) if k.lower() in {"retry-after", "content-type", "cache-control"}},
            "source": source,
        }

    def _extract_company_fields(self, item: dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
        title = str(item.get("title") or item.get("link") or "Unnamed company").strip()
        url = item.get("link") or item.get("formattedUrl")
        description = item.get("snippet") or item.get("htmlSnippet")
        if url:
            url = str(url).strip()
        return title, url, description

    def _build_companies(self, payload: dict, canonical_params: dict[str, Any]) -> list[LlmCompany]:
        items = payload.get("items") or []
        max_items = canonical_params.get("num_results") or len(items)
        selected = items[:max_items]
        companies: list[LlmCompany] = []
        for idx, item in enumerate(selected):
            name, url, description = self._extract_company_fields(item)
            if not url:
                continue
            confidence = max(0.6, 0.9 - (idx * 0.05))
            evidence = LlmEvidence(
                url=url,
                label=name,
                kind="homepage",
                snippet=description,
            )
            companies.append(
                LlmCompany(
                    name=name,
                    website_url=url,
                    description=description,
                    sector=None,
                    subsector=None,
                    hq_country=canonical_params.get("country"),
                    hq_city=None,
                    evidence=[evidence],
                    confidence=confidence,
                )
            )
        companies_sorted = sorted(companies, key=lambda c: c.name.lower())
        return companies_sorted

    def run(self, *, tenant_id: str, run_id: UUID, request: Optional[dict] = None) -> DiscoveryProviderResult:
        try:
            request_obj = self._normalize_params(request)
        except Exception as exc:  # noqa: BLE001
            return DiscoveryProviderResult(
                payload=None,
                provider=self.key,
                model="google_cse_v1",
                version=self.version,
                error={"code": "invalid_request", "message": str(exc)},
            )

        canonical_params = self._canonical_params(request_obj)

        fixture_payload, fixture_path = self._load_fixture()
        use_mock = bool(settings.ATS_MOCK_EXTERNAL_PROVIDERS)

        if use_mock and not fixture_payload:
            raise ExternalProviderConfigError(
                self.key,
                "Mock mode enabled but fixture missing",
                {"fixture_path": fixture_path or "scripts/fixtures/external/google_cse/default.json"},
            )

        api_key = settings.GOOGLE_CSE_API_KEY
        cx = settings.GOOGLE_CSE_CX

        if use_mock:
            status_code = 200
            response_payload = fixture_payload or {}
            headers = {}
            request_params = self._build_query_params(canonical_params, api_key or "mock_api_key", cx or "mock_cx")
            source_kind = "fixture"
        else:
            self.validate_config(allow_mock=False)
            request_params = self._build_query_params(canonical_params, api_key, cx)
            status_code, response_payload, headers = self._fetch_with_retry(request_params)
            source_kind = "api"

        if status_code != 200:
            envelope = self._build_envelope(
                canonical_params=canonical_params,
                request_params=request_params,
                response_payload=response_payload,
                status_code=status_code,
                headers=headers,
                source=source_kind,
            )
            message: str = "unexpected_error"
            if isinstance(response_payload, dict):
                if isinstance(response_payload.get("error"), dict):
                    message = response_payload.get("error", {}).get("message") or "upstream_error"
                else:
                    message = str(response_payload.get("error") or "upstream_error")
            return DiscoveryProviderResult(
                payload=None,
                provider=self.key,
                model="google_cse_v1",
                version=self.version,
                source_type="provider_json",
                envelope=envelope,
                error={"code": "upstream_error", "message": message, "status_code": status_code},
                raw_input_meta={"normalized_params": canonical_params, "fixture_path": fixture_path},
            )

        companies = self._build_companies(response_payload, canonical_params)

        run_context = LlmRunContext(
            query=canonical_params.get("query"),
            geo=[canonical_params["country"]] if canonical_params.get("country") else None,
            notes=f"tenant:{tenant_id}|run:{run_id}",
            industry=None,
        )

        payload = LlmDiscoveryPayload(
            provider=self.key,
            model="google_cse_v1",
            run_context=run_context,
            companies=companies,
        )

        envelope = self._build_envelope(
            canonical_params=canonical_params,
            request_params=request_params,
            response_payload=response_payload,
            status_code=status_code,
            headers=headers,
            source=source_kind,
        )

        return DiscoveryProviderResult(
            payload=payload,
            provider=self.key,
            model="google_cse_v1",
            version=self.version,
            source_type="provider_json",
            envelope=envelope,
            raw_input_meta={"normalized_params": canonical_params, "fixture_path": fixture_path},
        )


class XaiGrokProvider(DiscoveryProvider):
    """xAI Grok external LLM discovery provider with mock-first fixtures."""

    key = "xai_grok"
    version = "1"
    endpoint = "https://api.x.ai/v1/chat/completions"

    def __init__(self, *, fetcher: Optional[Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict, dict]]] = None, sleeper: Optional[Callable[[float], None]] = None):
        self.fetcher = fetcher or self._http_post
        self.sleeper = sleeper or time.sleep

    def validate_config(self, allow_mock: bool = True) -> None:
        if settings.ATS_MOCK_EXTERNAL_PROVIDERS and allow_mock:
            return

        _ensure_real_mode(
            self.key,
            [
                ("ATS_EXTERNAL_DISCOVERY_ENABLED", "1" if settings.ATS_EXTERNAL_DISCOVERY_ENABLED else None),
                ("XAI_API_KEY", settings.XAI_API_KEY),
            ],
        )

    def _normalize_params(self, request: XaiGrokProviderRequest | dict[str, Any] | None) -> XaiGrokProviderRequest:
        return XaiGrokProviderRequest.model_validate(request or {})

    def _canonical_params(self, request_obj: XaiGrokProviderRequest) -> dict[str, Any]:
        max_companies = request_obj.max_companies or 8
        max_companies = max(1, min(max_companies, 25))
        return {
            "query": request_obj.query,
            "industry": request_obj.industry,
            "region": request_obj.region,
            "max_companies": max_companies,
            "request_id": request_obj.request_id,
            "notes": request_obj.notes,
        }

    def _build_prompt(self, canonical_params: dict[str, Any]) -> str:
        query = canonical_params.get("query") or ""
        industry = canonical_params.get("industry")
        region = canonical_params.get("region")
        scope = []
        if industry:
            scope.append(f"industry={industry}")
        if region:
            scope.append(f"region={region}")
        scope_text = ", ".join(scope)
        return (
            "Return a JSON object with keys provider, model, run_context, companies. "
            "companies is an array of objects: name, website_url, hq_country, hq_city, sector, subsector, description, confidence, evidence[]. "
            "Each evidence entry should have url, label, kind (homepage|press_release|other), snippet. "
            f"Query: {query}. {scope_text}".strip()
        )

    def _build_request_body(self, canonical_params: dict[str, Any], model_name: str) -> dict[str, Any]:
        return {
            "model": model_name,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a deterministic research assistant. Return ONLY JSON with provider, model, run_context, companies.",
                },
                {
                    "role": "user",
                    "content": self._build_prompt(canonical_params),
                },
            ],
            "response_format": {"type": "json_object"},
        }

    def _http_post(self, url: str, json_body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict, dict[str, str]]:
        resp = httpx.post(url, json=json_body, headers=headers, timeout=30.0)
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            payload = {"text": resp.text}
        return resp.status_code, payload, dict(resp.headers)

    def _load_fixture(self) -> tuple[Optional[dict], Optional[str]]:
        fixture_path = os.getenv("XAI_GROK_FIXTURE_PATH")
        default_path = Path("scripts/fixtures/external/xai_grok/default.json")
        selected = None

        if fixture_path:
            selected = Path(fixture_path)
        elif default_path.exists():
            selected = default_path

        if selected and selected.exists():
            with open(selected, "r", encoding="utf-8") as handle:
                return json.load(handle), str(selected)
        return None, None

    def _parse_response_payload(self, payload: dict) -> dict:
        if payload is None:
            return {}
        if isinstance(payload, dict) and "choices" in payload:
            choices = payload.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content")
                if isinstance(content, str):
                    try:
                        return json.loads(content)
                    except Exception:  # noqa: BLE001
                        return {"content": content}
        return payload

    def _build_companies(self, parsed_payload: dict) -> list[LlmCompany]:
        companies_raw = parsed_payload.get("companies") or []
        companies: list[LlmCompany] = []
        for entry in companies_raw:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            evidence_entries: list[LlmEvidence] = []
            for ev in entry.get("evidence") or []:
                url = ev.get("url")
                if not url:
                    continue
                evidence_entries.append(
                    LlmEvidence(
                        url=url,
                        label=ev.get("label") or ev.get("kind") or "evidence",
                        kind=ev.get("kind") or "homepage",
                        snippet=ev.get("snippet"),
                    )
                )

            companies.append(
                LlmCompany(
                    name=name,
                    website_url=entry.get("website_url") or entry.get("url"),
                    hq_country=entry.get("hq_country") or entry.get("country"),
                    hq_city=entry.get("hq_city"),
                    sector=entry.get("sector"),
                    subsector=entry.get("subsector"),
                    description=entry.get("description"),
                    confidence=entry.get("confidence"),
                    evidence=evidence_entries or None,
                )
            )

        return sorted(companies, key=lambda c: c.name.lower())

    def run(self, *, tenant_id: str, run_id: UUID, request: Optional[dict] = None) -> DiscoveryProviderResult:
        try:
            request_obj = self._normalize_params(request)
        except Exception as exc:  # noqa: BLE001
            return DiscoveryProviderResult(
                payload=None,
                provider=self.key,
                model=settings.XAI_MODEL or "grok-2",
                version=self.version,
                source_type="llm_json",
                error={"code": "invalid_request", "message": str(exc)},
            )

        canonical_params = self._canonical_params(request_obj)
        fixture_payload, fixture_path = self._load_fixture()
        use_mock = bool(settings.ATS_MOCK_EXTERNAL_PROVIDERS)

        if use_mock and not fixture_payload:
            raise ExternalProviderConfigError(
                self.key,
                "Mock mode enabled but fixture missing",
                {"fixture_path": fixture_path or "scripts/fixtures/external/xai_grok/default.json"},
            )

        model_name = settings.XAI_MODEL or "grok-2"
        request_body = self._build_request_body(canonical_params, model_name)

        if use_mock:
            status_code = 200
            response_payload = fixture_payload or {}
            headers: dict[str, str] = {}
            source_kind = "fixture"
        else:
            self.validate_config(allow_mock=False)
            headers_in = {"Authorization": f"Bearer {settings.XAI_API_KEY}"}
            status_code, response_payload, headers = self.fetcher(self.endpoint, request_body, headers_in)
            source_kind = "api"

        parsed_response = self._parse_response_payload(response_payload)

        if status_code != 200:
            envelope = {
                "provider_key": self.key,
                "normalized_params": canonical_params,
                "request": {"endpoint": self.endpoint, "body": request_body},
                "response": response_payload,
                "response_status": status_code,
                "response_headers": headers,
                "source": source_kind,
            }
            return DiscoveryProviderResult(
                payload=None,
                provider=self.key,
                model=model_name,
                version=self.version,
                source_type="llm_json",
                envelope=envelope,
                error={"code": "upstream_error", "message": "xAI Grok returned non-200", "status_code": status_code},
                raw_input_text=json.dumps(request_body, sort_keys=True),
                raw_input_meta={"normalized_params": canonical_params, "fixture_path": fixture_path},
            )

        companies = self._build_companies(parsed_response)
        run_context = LlmRunContext(
            query=canonical_params.get("query"),
            geo=[canonical_params["region"]] if canonical_params.get("region") else None,
            industry=[canonical_params["industry"]] if canonical_params.get("industry") else None,
            notes=f"tenant:{tenant_id}|run:{run_id}",
        )

        payload = LlmDiscoveryPayload(
            provider=self.key,
            model=model_name,
            run_context=run_context,
            companies=companies,
        )

        envelope = {
            "provider_key": self.key,
            "normalized_params": canonical_params,
            "request": {"endpoint": self.endpoint, "body": request_body},
            "response": response_payload,
            "response_status": status_code,
            "response_headers": {k: headers.get(k) for k in (headers or {})},
            "source": source_kind,
        }

        return DiscoveryProviderResult(
            payload=payload,
            provider=self.key,
            model=model_name,
            version=self.version,
            source_type="llm_json",
            envelope=envelope,
            raw_input_text=json.dumps(request_body, sort_keys=True),
            raw_input_meta={"normalized_params": canonical_params, "fixture_path": fixture_path},
        )


def get_discovery_provider(provider_key: str) -> Optional[DiscoveryProvider]:
    """Lookup a discovery provider by key."""
    return _PROVIDER_REGISTRY.get(provider_key)


def list_discovery_providers() -> Dict[str, str]:
    """Return available providers and their versions."""
    return {key: provider.version for key, provider in _PROVIDER_REGISTRY.items()}


_google_provider = GoogleSearchProvider()
_xai_provider = XaiGrokProvider()

_PROVIDER_REGISTRY: Dict[str, DiscoveryProvider] = {
    DeterministicDiscoveryProvider.key: DeterministicDiscoveryProvider(),
    SeedListProvider.key: SeedListProvider(),
    GoogleSearchProvider.key: _google_provider,
    "google_search": _google_provider,
    XaiGrokProvider.key: _xai_provider,
}

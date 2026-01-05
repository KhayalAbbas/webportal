"""
Deterministic company enrichment extraction (Stage 7.2).

Rules-only extractor that reads `ResearchSourceDocument.content_text` and emits
evidence-backed enrichment assignments for canonical companies. No LLM usage,
strictly pattern/keyword-based with controlled vocabularies and stable ordering
to guarantee idempotency across runs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.company_research_repo import CompanyResearchRepository
from app.schemas.enrichment_assignment import EnrichmentAssignmentCreate, EnrichmentAssignmentRead
from app.services.enrichment_assignment_service import EnrichmentAssignmentService


@dataclass(frozen=True)
class HQCountryMatch:
    country: str
    confidence: float
    pattern: str


@dataclass(frozen=True)
class OwnershipMatch:
    signal: str
    confidence: float
    phrase: str


@dataclass(frozen=True)
class IndustryKeywordsMatch:
    keywords: list[str]
    confidence: float


class CompanyEnrichmentExtractionService:
    """Rule-based company enrichment extractor.

    Extracts HQ country, ownership signal, and industry keywords from a single
    source document. Every assignment references `source_document_id`, uses a
    deterministic `input_scope_hash`, and is persisted via the Stage 7.1
    `EnrichmentAssignmentService` for idempotent writes.
    """

    DERIVED_BY = "company_enrichment_extraction_v7_2"
    INPUT_SCOPE_SALT = "phase_7_2_rules_v1"

    # Controlled country map -> synonyms. Canonical value is the dict key.
    COUNTRY_SYNONYMS: dict[str, list[str]] = {
        "United States": ["united states", "usa", "u.s.a", "us", "u.s"],
        "United Kingdom": ["united kingdom", "uk", "u.k", "great britain", "britain"],
        "United Arab Emirates": ["united arab emirates", "uae"],
        "Saudi Arabia": ["saudi arabia", "saudi", "ksa"],
        "Qatar": ["qatar"],
        "Kuwait": ["kuwait"],
        "Oman": ["oman"],
        "Bahrain": ["bahrain"],
        "Romania": ["romania"],
        "Republic of Moldova": ["moldova", "republic of moldova"],
        "India": ["india"],
        "Pakistan": ["pakistan"],
        "Singapore": ["singapore"],
        "China": ["china", "prc"],
        "Japan": ["japan"],
        "South Korea": ["south korea", "korea"],
        "Vietnam": ["vietnam"],
        "Thailand": ["thailand"],
        "Indonesia": ["indonesia"],
        "Malaysia": ["malaysia"],
        "Philippines": ["philippines", "philippine"],
        "Australia": ["australia"],
        "New Zealand": ["new zealand"],
        "Canada": ["canada"],
        "Mexico": ["mexico"],
        "Brazil": ["brazil"],
        "Argentina": ["argentina"],
        "Chile": ["chile"],
        "Colombia": ["colombia"],
        "Peru": ["peru"],
        "Germany": ["germany"],
        "France": ["france"],
        "Spain": ["spain"],
        "Portugal": ["portugal"],
        "Italy": ["italy"],
        "Switzerland": ["switzerland"],
        "Netherlands": ["netherlands", "holland"],
        "Belgium": ["belgium"],
        "Sweden": ["sweden"],
        "Norway": ["norway"],
        "Denmark": ["denmark"],
        "Finland": ["finland"],
        "Poland": ["poland"],
        "Czech Republic": ["czech republic", "czechia"],
        "Hungary": ["hungary"],
        "Greece": ["greece"],
        "Turkey": ["turkey", "turkiye"],
        "Ireland": ["ireland"],
        "Israel": ["israel"],
        "Egypt": ["egypt"],
        "Kenya": ["kenya"],
        "Nigeria": ["nigeria"],
        "South Africa": ["south africa"],
    }

    # HQ extraction patterns with rubric-specific confidence.
    HQ_PATTERNS: list[tuple[re.Pattern[str], float, str]] = [
        (re.compile(r"\bheadquarters?:?\s*(?P<loc>[A-Za-z .,'-]+)", re.IGNORECASE), 0.90, "headquarters"),
        (re.compile(r"\bhq:?\s*(?P<loc>[A-Za-z .,'-]+)", re.IGNORECASE), 0.90, "hq"),
        (re.compile(r"\bbased in\s+(?P<loc>[A-Za-z .,'-]+)", re.IGNORECASE), 0.70, "based in"),
        (re.compile(r"\blocated in\s+(?P<loc>[A-Za-z .,'-]+)", re.IGNORECASE), 0.70, "located in"),
    ]

    OWNERSHIP_PRIORITY = ["state_owned", "public_company", "subsidiary", "private_company"]

    OWNERSHIP_RULES: list[tuple[str, float, list[re.Pattern[str]]]] = [
        (
            "public_company",
            0.80,
            [
                re.compile(r"\blisted on\b", re.IGNORECASE),
                re.compile(r"\btraded on\b", re.IGNORECASE),
                re.compile(r"\bticker\b", re.IGNORECASE),
                re.compile(r"\bnyse\b", re.IGNORECASE),
                re.compile(r"\bnasdaq\b", re.IGNORECASE),
                re.compile(r"\blse\b", re.IGNORECASE),
            ],
        ),
        (
            "subsidiary",
            0.80,
            [
                re.compile(r"\bsubsidiary of\b", re.IGNORECASE),
                re.compile(r"\bwholly owned subsidiary\b", re.IGNORECASE),
            ],
        ),
        (
            "subsidiary",
            0.60,
            [re.compile(r"\bpart of the\b", re.IGNORECASE)],
        ),
        (
            "private_company",
            0.80,
            [
                re.compile(r"\bprivately held\b", re.IGNORECASE),
                re.compile(r"\bprivate company\b", re.IGNORECASE),
            ],
        ),
        (
            "state_owned",
            0.80,
            [
                re.compile(r"\bstate[- ]owned\b", re.IGNORECASE),
                re.compile(r"\bgovernment[- ]owned\b", re.IGNORECASE),
                re.compile(r"\bsoe\b", re.IGNORECASE),
            ],
        ),
    ]

    # Controlled keyword dictionary (phrases kept compact to avoid false positives).
    INDUSTRY_KEYWORDS: list[str] = [
        "renewable energy",
        "solar",
        "wind",
        "hydrogen",
        "battery",
        "energy storage",
        "grid",
        "power generation",
        "oil",
        "gas",
        "lng",
        "petrochemical",
        "mining",
        "metals",
        "steel",
        "construction",
        "cement",
        "real estate",
        "infrastructure",
        "logistics",
        "supply chain",
        "shipping",
        "aviation",
        "aerospace",
        "defense",
        "automotive",
        "mobility",
        "transportation",
        "rail",
        "semiconductor",
        "electronics",
        "hardware",
        "robotics",
        "automation",
        "manufacturing",
        "industrial equipment",
        "chemicals",
        "fertilizer",
        "agriculture",
        "food processing",
        "beverage",
        "retail",
        "ecommerce",
        "fintech",
        "payments",
        "banking",
        "insurance",
        "investment",
        "asset management",
        "healthcare",
        "hospital",
        "pharma",
        "biotech",
        "medtech",
        "life sciences",
        "education",
        "media",
        "entertainment",
        "gaming",
        "sports",
        "telecom",
        "iot",
        "smart city",
        "cloud",
        "saas",
        "data analytics",
        "ai",
        "machine learning",
        "cybersecurity",
        "blockchain",
        "water treatment",
        "waste management",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db
        self.research_repo = CompanyResearchRepository(db)
        self.assignment_service = EnrichmentAssignmentService(db)

    async def extract_company_enrichment(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
        source_document_id: UUID,
    ) -> List[EnrichmentAssignmentRead]:
        """Run deterministic extraction for one source document.

        - HQ country: only emits on explicit location headers and controlled country list.
        - Ownership signal: phrase-based mapping with confidence rubric and tie-breaker.
        - Industry keywords: bounded list with whole-word matching and deterministic sorting.
        """

        source = await self.research_repo.get_source_document(tenant_id, source_document_id)
        if not source:
            raise ValueError("source_document_not_found")

        content = (source.content_text or "").strip()
        if not content:
            return []

        assignments: list[EnrichmentAssignmentCreate] = []

        hq_match = self._extract_hq_country(content)
        if hq_match:
            assignments.append(
                self._build_assignment(
                    tenant_id=tenant_id,
                    canonical_company_id=canonical_company_id,
                    source_document_id=source_document_id,
                    field_key="hq_country",
                    value=hq_match.country,
                    confidence=hq_match.confidence,
                    value_normalized=hq_match.country,
                )
            )

        ownership_match = self._extract_ownership_signal(content)
        if ownership_match:
            assignments.append(
                self._build_assignment(
                    tenant_id=tenant_id,
                    canonical_company_id=canonical_company_id,
                    source_document_id=source_document_id,
                    field_key="ownership_signal",
                    value=ownership_match.signal,
                    confidence=ownership_match.confidence,
                    value_normalized=ownership_match.signal,
                )
            )

        industry_match = self._extract_industry_keywords(content)
        if industry_match:
            assignments.append(
                self._build_assignment(
                    tenant_id=tenant_id,
                    canonical_company_id=canonical_company_id,
                    source_document_id=source_document_id,
                    field_key="industry_keywords",
                    value=industry_match.keywords,
                    confidence=industry_match.confidence,
                    value_normalized=", ".join(industry_match.keywords),
                )
            )

        if not assignments:
            return []

        return await self.assignment_service.record_assignments(tenant_id, assignments)

    def _build_assignment(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
        source_document_id: UUID,
        field_key: str,
        value: object,
        confidence: float,
        value_normalized: Optional[str] = None,
    ) -> EnrichmentAssignmentCreate:
        return EnrichmentAssignmentCreate(
            tenant_id=tenant_id,
            target_entity_type="company",
            target_canonical_id=canonical_company_id,
            field_key=field_key,
            value=value,
            value_normalized=value_normalized,
            confidence=confidence,
            derived_by=self.DERIVED_BY,
            source_document_id=source_document_id,
            input_scope_hash=self._input_scope_hash(source_document_id, field_key),
        )

    def _input_scope_hash(self, source_document_id: UUID, field_key: str) -> str:
        base = f"{self.INPUT_SCOPE_SALT}:{source_document_id}:{field_key}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _extract_hq_country(self, text: str) -> Optional[HQCountryMatch]:
        # Use lower text for matching; stop at first deterministic hit with allowed country.
        normalized_text = text.lower()
        for pattern, confidence, label in self.HQ_PATTERNS:
            match = pattern.search(normalized_text)
            if not match:
                continue
            location_fragment = match.group("loc") or ""
            country = self._match_country_name(location_fragment)
            if country:
                return HQCountryMatch(country=country, confidence=confidence, pattern=label)
        return None

    def _match_country_name(self, location_fragment: str) -> Optional[str]:
        cleaned = re.sub(r"[^a-zA-Z\s]", " ", location_fragment.lower())
        cleaned = " ".join(cleaned.split())
        for country in sorted(self.COUNTRY_SYNONYMS.keys()):
            for synonym in self.COUNTRY_SYNONYMS[country]:
                if re.search(rf"\b{re.escape(synonym)}\b", cleaned):
                    return country
        return None

    def _extract_ownership_signal(self, text: str) -> Optional[OwnershipMatch]:
        normalized = text.lower()
        best: Optional[OwnershipMatch] = None
        for signal, confidence, patterns in self.OWNERSHIP_RULES:
            for pattern in patterns:
                if pattern.search(normalized):
                    candidate = OwnershipMatch(signal=signal, confidence=confidence, phrase=pattern.pattern)
                    best = self._choose_stronger(best, candidate)
                    break
        return best

    def _choose_stronger(
        self,
        current: Optional[OwnershipMatch],
        incoming: OwnershipMatch,
    ) -> OwnershipMatch:
        if current is None:
            return incoming
        if incoming.confidence > current.confidence:
            return incoming
        if incoming.confidence < current.confidence:
            return current
        # Tie: prefer deterministic priority order.
        current_rank = self.OWNERSHIP_PRIORITY.index(current.signal)
        incoming_rank = self.OWNERSHIP_PRIORITY.index(incoming.signal)
        if incoming_rank < current_rank:
            return incoming
        return current

    def _extract_industry_keywords(self, text: str) -> Optional[IndustryKeywordsMatch]:
        normalized = text.lower()
        matches: list[tuple[str, int]] = []
        for keyword in self.INDUSTRY_KEYWORDS:
            pattern = rf"\b{re.escape(keyword.lower())}\b"
            occurrences = len(re.findall(pattern, normalized))
            if occurrences > 0:
                matches.append((keyword, occurrences))

        if not matches:
            return None

        # Sort by frequency desc then keyword alpha for determinism.
        matches.sort(key=lambda item: (-item[1], item[0]))
        top_keywords = [kw for kw, _ in matches[:10]]
        max_frequency = max(count for _, count in matches)
        confidence = 0.70 if max_frequency >= 2 else 0.60
        return IndustryKeywordsMatch(keywords=top_keywords, confidence=confidence)


__all__ = ["CompanyEnrichmentExtractionService"]
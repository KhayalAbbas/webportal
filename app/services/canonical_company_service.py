import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_research import CompanyProspect, CanonicalCompany
from app.repositories.company_research_repo import CompanyResearchRepository


class CanonicalCompanyService:
    """Tenant-wide canonical company resolver (Stage 6.3)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)

    async def resolve_run_companies(self, tenant_id: str, run_id: UUID) -> dict:
        driver_prospects = await self.repo.list_company_prospects_for_run_with_website(tenant_id, run_id)
        driver_name_country = [p for p in await self.repo.list_company_prospects_with_country(tenant_id) if p.company_research_run_id == run_id and not p.website_url]

        all_domain_prospects = await self.repo.list_company_prospects_with_website(tenant_id)
        domain_map: Dict[str, List[CompanyProspect]] = defaultdict(list)
        for prospect in all_domain_prospects:
            norm = self._normalize_domain(prospect.website_url)
            if norm:
                domain_map[norm].append(prospect)

        name_country_map: Dict[Tuple[str, str], List[CompanyProspect]] = defaultdict(list)
        for prospect in await self.repo.list_company_prospects_with_country(tenant_id):
            if prospect.website_url:
                continue
            name_norm = self._normalize_name(prospect.name_normalized or prospect.name_raw)
            country = (prospect.hq_country or "").strip().upper()
            if name_norm and country:
                name_country_map[(name_norm, country)].append(prospect)

        all_ids = [p.id for p in all_domain_prospects] + [p.id for p in driver_name_country]
        evidence_rows = await self.repo.list_company_evidence_for_prospect_ids(tenant_id, list(set(all_ids)))
        evidence_map = self._build_evidence_map(evidence_rows)

        existing_links = await self.repo.list_canonical_company_links(tenant_id)
        existing_link_entity_ids: Set[UUID] = {l.company_entity_id for l in existing_links}

        summary = {
            "companies_scanned": len(driver_prospects) + len(driver_name_country),
            "canonical_companies_created": 0,
            "canonical_companies_matched": 0,
            "canonical_company_links_created": 0,
            "canonical_company_links_existing": 0,
            "conflicts_skipped": 0,
            "evidence_missing_skipped": 0,
            "warnings_multi_evidence": 0,
            "multi_evidence_deterministic_choice": 0,
        }

        # Domain-first resolution
        for prospect in driver_prospects:
            domain_norm = self._normalize_domain(prospect.website_url)
            if not domain_norm:
                continue

            canonical = await self.repo.get_canonical_company_by_domain(tenant_id, domain_norm)
            if canonical:
                summary["canonical_companies_matched"] += 1
            else:
                canonical = await self.repo.create_canonical_company(
                    tenant_id=tenant_id,
                    canonical_name=self._normalize_name(prospect.name_normalized or prospect.name_raw),
                    primary_domain=domain_norm,
                    country_code=prospect.hq_country,
                )
                summary["canonical_companies_created"] += 1

            await self.repo.upsert_canonical_company_domain(tenant_id, canonical.id, domain_norm)
            await self._link_prospect(
                tenant_id=tenant_id,
                canonical_company_id=canonical.id,
                prospect=prospect,
                match_rule="domain",
                evidence_map=evidence_map,
                existing_link_entity_ids=existing_link_entity_ids,
                summary=summary,
            )

            for peer in domain_map.get(domain_norm, []):
                await self._link_prospect(
                    tenant_id=tenant_id,
                    canonical_company_id=canonical.id,
                    prospect=peer,
                    match_rule="domain",
                    evidence_map=evidence_map,
                    existing_link_entity_ids=existing_link_entity_ids,
                    summary=summary,
                )

        # Name + country resolution (only when country exists and no domain)
        for prospect in driver_name_country:
            name_norm = self._normalize_name(prospect.name_normalized or prospect.name_raw)
            country = (prospect.hq_country or "").strip().upper()
            if not name_norm or not country:
                continue

            canonical = await self.repo.get_canonical_company_by_name_country(
                tenant_id=tenant_id,
                name_normalized=name_norm,
                country_code=country,
            )
            if canonical:
                summary["canonical_companies_matched"] += 1
            else:
                canonical = await self.repo.create_canonical_company(
                    tenant_id=tenant_id,
                    canonical_name=name_norm,
                    primary_domain=None,
                    country_code=country,
                )
                summary["canonical_companies_created"] += 1

            for peer in name_country_map.get((name_norm, country), []):
                await self._link_prospect(
                    tenant_id=tenant_id,
                    canonical_company_id=canonical.id,
                    prospect=peer,
                    match_rule="name_country",
                    evidence_map=evidence_map,
                    existing_link_entity_ids=existing_link_entity_ids,
                    summary=summary,
                )

        return summary

    def _build_evidence_map(self, rows) -> Dict[UUID, List[UUID]]:
        evidence_map: Dict[UUID, List[UUID]] = defaultdict(list)
        for row in rows:
            if row.source_document_id:
                evidence_map[row.company_prospect_id].append(row.source_document_id)
        return evidence_map

    def _select_evidence_id(self, evidence_ids: List[UUID]) -> tuple[Optional[UUID], bool]:
        if not evidence_ids:
            return None, False
        if len(evidence_ids) == 1:
            return evidence_ids[0], False
        sorted_ids = sorted(evidence_ids, key=lambda x: str(x))
        return sorted_ids[0], True

    def _normalize_domain(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url if "://" in url else f"http://{url}")
            host = parsed.hostname or ""
        except ValueError:
            return None
        host = host.lower().strip().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return None
        return host

    def _normalize_name(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        norm = " ".join(str(name).strip().split())
        return norm.lower() if norm else None

    async def _link_prospect(
        self,
        tenant_id: str,
        canonical_company_id: UUID,
        prospect: CompanyProspect,
        match_rule: str,
        evidence_map: Dict[UUID, List[UUID]],
        existing_link_entity_ids: Set[UUID],
        summary: dict,
    ) -> None:
        evidence_ids = evidence_map.get(prospect.id, [])
        if not evidence_ids:
            summary["evidence_missing_skipped"] += 1
            summary["conflicts_skipped"] += 1
            return

        evidence_id, multi = self._select_evidence_id(evidence_ids)
        if not evidence_id:
            summary["conflicts_skipped"] += 1
            summary["evidence_missing_skipped"] += 1
            return
        if multi:
            summary["warnings_multi_evidence"] += 1
            summary["multi_evidence_deterministic_choice"] += 1
            summary["conflicts_skipped"] += 1

        link = await self.repo.upsert_canonical_company_link(
            tenant_id=tenant_id,
            canonical_company_id=canonical_company_id,
            company_entity_id=prospect.id,
            match_rule=match_rule,
            evidence_source_document_id=evidence_id,
            evidence_company_research_run_id=prospect.company_research_run_id,
        )

        if prospect.id in existing_link_entity_ids:
            summary["canonical_company_links_existing"] += 1
        else:
            summary["canonical_company_links_created"] += 1
            existing_link_entity_ids.add(prospect.id)

        return

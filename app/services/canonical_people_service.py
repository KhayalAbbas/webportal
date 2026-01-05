import re
import uuid
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.company_research import (
    ExecutiveProspect,
    CanonicalPerson,
    CanonicalPersonLink,
)
from app.repositories.company_research_repo import CompanyResearchRepository


class CanonicalPeopleService:
    """Tenant-wide canonical people resolver (Stage 6.2)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)

    async def resolve_run_people(self, tenant_id: str, run_id: UUID) -> dict:
        executives = await self.repo.list_executive_prospects_for_run(tenant_id, run_id)
        evidence_rows = await self.repo.list_executive_evidence_for_run(tenant_id, run_id)
        evidence_map = self._build_evidence_map(evidence_rows)

        existing_links = await self.repo.list_canonical_person_links(tenant_id)
        existing_link_person_ids: Set[UUID] = {l.person_entity_id for l in existing_links}

        summary = {
            "executives_scanned": len(executives),
            "canonical_people_created": 0,
            "canonical_people_matched": 0,
            "canonical_person_links_created": 0,
            "canonical_person_links_existing": 0,
            "conflicts_skipped": 0,
            "evidence_missing_skipped": 0,
            "warnings_multi_evidence": 0,
            "multi_evidence_deterministic_choice": 0,
        }

        handled_emails: Set[str] = set()
        handled_linkedin: Set[str] = set()

        for exec_row in executives:
            email_norm = self._normalize_email(exec_row.email)
            linkedin_norm = self._normalize_linkedin(exec_row.linkedin_url)

            if email_norm:
                if email_norm in handled_emails:
                    continue
                await self._process_email_group(
                    tenant_id=tenant_id,
                    email_norm=email_norm,
                    default_exec=exec_row,
                    existing_link_person_ids=existing_link_person_ids,
                    summary=summary,
                )
                handled_emails.add(email_norm)
                continue

            if linkedin_norm:
                if linkedin_norm in handled_linkedin:
                    continue
                await self._process_linkedin_group(
                    tenant_id=tenant_id,
                    linkedin_norm=linkedin_norm,
                    default_exec=exec_row,
                    existing_link_person_ids=existing_link_person_ids,
                    summary=summary,
                )
                handled_linkedin.add(linkedin_norm)
                continue

            await self._process_name_company(
                tenant_id=tenant_id,
                exec_row=exec_row,
                evidence_map=evidence_map,
                existing_link_person_ids=existing_link_person_ids,
                summary=summary,
            )

        return summary

    async def _process_email_group(
        self,
        tenant_id: str,
        email_norm: str,
        default_exec: ExecutiveProspect,
        existing_link_person_ids: Set[UUID],
        summary: dict,
    ) -> None:
        execs = await self.repo.list_executive_prospects_by_email(tenant_id, email_norm)
        evidence_rows = await self.repo.list_executive_evidence_for_exec_ids(tenant_id, [e.id for e in execs])
        evidence_map = self._build_evidence_map(evidence_rows)

        canonical = await self.repo.get_canonical_person_by_email(tenant_id, email_norm)
        if canonical:
            summary["canonical_people_matched"] += 1
        else:
            canonical = await self.repo.create_canonical_person(
                tenant_id=tenant_id,
                canonical_full_name=self._normalize_person_name(default_exec.name_normalized or default_exec.name_raw),
                primary_email=email_norm,
                primary_linkedin_url=self._normalize_linkedin(default_exec.linkedin_url),
            )
            summary["canonical_people_created"] += 1

        await self.repo.upsert_canonical_person_email(tenant_id, canonical.id, email_norm)

        for exec_row in execs:
            evidence_ids = self._collect_evidence_ids(exec_row, evidence_map)
            if not evidence_ids:
                summary["evidence_missing_skipped"] += 1
                summary["conflicts_skipped"] += 1
                continue
            evidence_id, multi = self._select_evidence_id(evidence_ids)
            if multi:
                summary["warnings_multi_evidence"] += 1
                summary["multi_evidence_deterministic_choice"] += 1

            link = await self.repo.upsert_canonical_person_link(
                tenant_id=tenant_id,
                canonical_person_id=canonical.id,
                person_entity_id=exec_row.id,
                match_rule="email",
                evidence_source_document_id=evidence_id,
                evidence_company_research_run_id=exec_row.company_research_run_id,
            )

            if exec_row.id in existing_link_person_ids:
                summary["canonical_person_links_existing"] += 1
            else:
                summary["canonical_person_links_created"] += 1
                existing_link_person_ids.add(exec_row.id)

    async def _process_linkedin_group(
        self,
        tenant_id: str,
        linkedin_norm: str,
        default_exec: ExecutiveProspect,
        existing_link_person_ids: Set[UUID],
        summary: dict,
    ) -> None:
        execs = await self.repo.list_executive_prospects_by_linkedin(tenant_id, linkedin_norm)
        evidence_rows = await self.repo.list_executive_evidence_for_exec_ids(tenant_id, [e.id for e in execs])
        evidence_map = self._build_evidence_map(evidence_rows)

        canonical = await self.repo.get_canonical_person_by_linkedin(tenant_id, linkedin_norm)
        if canonical:
            summary["canonical_people_matched"] += 1
        else:
            canonical = await self.repo.create_canonical_person(
                tenant_id=tenant_id,
                canonical_full_name=self._normalize_person_name(default_exec.name_normalized or default_exec.name_raw),
                primary_linkedin_url=linkedin_norm,
            )
            summary["canonical_people_created"] += 1

        for exec_row in execs:
            evidence_ids = self._collect_evidence_ids(exec_row, evidence_map)
            if not evidence_ids:
                summary["evidence_missing_skipped"] += 1
                summary["conflicts_skipped"] += 1
                continue
            evidence_id, multi = self._select_evidence_id(evidence_ids)
            if multi:
                summary["warnings_multi_evidence"] += 1
                summary["multi_evidence_deterministic_choice"] += 1

            link = await self.repo.upsert_canonical_person_link(
                tenant_id=tenant_id,
                canonical_person_id=canonical.id,
                person_entity_id=exec_row.id,
                match_rule="linkedin",
                evidence_source_document_id=evidence_id,
                evidence_company_research_run_id=exec_row.company_research_run_id,
            )

            if exec_row.id in existing_link_person_ids:
                summary["canonical_person_links_existing"] += 1
            else:
                summary["canonical_person_links_created"] += 1
                existing_link_person_ids.add(exec_row.id)

    async def _process_name_company(
        self,
        tenant_id: str,
        exec_row: ExecutiveProspect,
        evidence_map: Dict[UUID, List[UUID]],
        existing_link_person_ids: Set[UUID],
        summary: dict,
    ) -> None:
        evidence_ids = self._collect_evidence_ids(exec_row, evidence_map)
        if not evidence_ids:
            summary["evidence_missing_skipped"] += 1
            summary["conflicts_skipped"] += 1
            return

        evidence_id, multi = self._select_evidence_id(evidence_ids)
        if multi:
            summary["warnings_multi_evidence"] += 1
            summary["multi_evidence_deterministic_choice"] += 1

        # Strict name + company_prospect match via existing links
        name_norm = self._normalize_person_name(exec_row.name_normalized or exec_row.name_raw)
        if not name_norm or not exec_row.company_prospect_id:
            summary["conflicts_skipped"] += 1
            return

        canonical, multiple = await self._find_canonical_by_name_and_company(
            tenant_id=tenant_id,
            name_normalized=name_norm,
            company_prospect_id=exec_row.company_prospect_id,
        )
        if multiple:
            summary["conflicts_skipped"] += 1
            return
        if canonical:
            summary["canonical_people_matched"] += 1
        else:
            canonical = await self.repo.create_canonical_person(
                tenant_id=tenant_id,
                canonical_full_name=name_norm,
            )
            summary["canonical_people_created"] += 1

        link = await self.repo.upsert_canonical_person_link(
            tenant_id=tenant_id,
            canonical_person_id=canonical.id,
            person_entity_id=exec_row.id,
            match_rule="name_company",
            evidence_source_document_id=evidence_id,
            evidence_company_research_run_id=exec_row.company_research_run_id,
        )

        if exec_row.id in existing_link_person_ids:
            summary["canonical_person_links_existing"] += 1
        else:
            summary["canonical_person_links_created"] += 1
            existing_link_person_ids.add(exec_row.id)

    async def _find_canonical_by_name_and_company(
        self,
        tenant_id: str,
        name_normalized: str,
        company_prospect_id: UUID,
    ) -> tuple[Optional[CanonicalPerson], bool]:
        query = (
            select(CanonicalPerson)
            .join(CanonicalPersonLink, CanonicalPersonLink.canonical_person_id == CanonicalPerson.id)
            .join(ExecutiveProspect, ExecutiveProspect.id == CanonicalPersonLink.person_entity_id)
            .where(
                CanonicalPerson.tenant_id == tenant_id,
                CanonicalPersonLink.tenant_id == tenant_id,
                ExecutiveProspect.company_prospect_id == company_prospect_id,
                func.lower(ExecutiveProspect.name_normalized) == name_normalized.lower(),
            )
            .limit(2)
        )
        result = await self.db.execute(query)
        rows = result.scalars().all()
        if len(rows) > 1:
            return None, True
        if not rows:
            return None, False
        return rows[0], False

    def _build_evidence_map(self, evidence_rows: List) -> Dict[UUID, List[UUID]]:
        mapping: Dict[UUID, List[UUID]] = {}
        for ev in evidence_rows:
            if not ev.source_document_id:
                continue
            mapping.setdefault(ev.executive_prospect_id, []).append(ev.source_document_id)
        return mapping

    def _collect_evidence_ids(
        self,
        exec_row: ExecutiveProspect,
        evidence_map: Dict[UUID, List[UUID]],
    ) -> List[UUID]:
        collected: Set[UUID] = set()
        if exec_row.source_document_id:
            collected.add(exec_row.source_document_id)
        for ev_id in evidence_map.get(exec_row.id, []):
            collected.add(ev_id)
        return sorted(collected, key=lambda x: str(x))

    def _select_evidence_id(self, evidence_ids: List[UUID]) -> tuple[UUID, bool]:
        if not evidence_ids:
            raise ValueError("evidence_ids_empty")
        sorted_ids = sorted(evidence_ids, key=lambda x: str(x))
        return sorted_ids[0], len(sorted_ids) > 1

    def _normalize_email(self, email: Optional[str]) -> str:
        if not email:
            return ""
        return email.strip().lower()

    def _normalize_person_name(self, name: Optional[str]) -> str:
        if not name:
            return ""
        lowered = name.lower()
        cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
        return " ".join(cleaned.split())

    def _normalize_linkedin(self, url: Optional[str]) -> str:
        if not url:
            return ""
        parsed = urlparse(url.strip())
        if not parsed.scheme:
            parsed = parsed._replace(scheme="https")
        normalized_netloc = parsed.netloc.lower()
        normalized_path = parsed.path.rstrip("/")
        cleaned = parsed._replace(netloc=normalized_netloc, path=normalized_path, params="", query="", fragment="")
        normalized = urlunparse(cleaned)
        return normalized.lower()

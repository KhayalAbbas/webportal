import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_research import ExecutiveProspect, ExecutiveProspectEvidence
from app.repositories.company_research_repo import CompanyResearchRepository


class EntityResolutionService:
    """Deterministic, run-scoped entity resolver with evidence-first merges."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)

    async def resolve_run_entities(self, tenant_id: str, run_id: UUID, dry_run: bool = False) -> dict:
        entity_type = "executive"
        executives = await self.repo.list_executive_prospects_for_run(tenant_id, run_id)
        evidence_rows = await self.repo.list_executive_evidence_for_run(tenant_id, run_id)

        evidence_map = self._build_evidence_map(evidence_rows)
        groups = self._group_executives(executives)

        existing_resolved = await self.repo.list_resolved_entities_for_run(tenant_id, run_id, entity_type=entity_type)
        existing_links = await self.repo.list_entity_merge_links_for_run(tenant_id, run_id, entity_type=entity_type)

        existing_resolved_hashes = {r.resolution_hash for r in existing_resolved}
        existing_link_pairs = {(l.canonical_entity_id, l.duplicate_entity_id) for l in existing_links}

        summary = {
            "entity_type": entity_type,
            "executives_scanned": len(executives),
            "groups_considered": len(groups),
            "resolved_groups": 0,
            "merge_links_written": 0,
            "merge_links_existing": 0,
            "skipped": False,
        }

        if not executives:
            summary["skipped"] = True
            summary["reason"] = "no_executives"
            return summary

        if not groups:
            summary["skipped"] = True
            summary["reason"] = "no_groups"
            return summary

        for key, members in groups.items():
            if len(members) < 2:
                continue

            canonical = sorted(members, key=self._canonical_sort_key)[0]
            reason_codes = self._reason_codes_for_key(key)
            match_keys = self._match_keys_for_key(key)
            evidence_ids = self._collect_evidence_ids(members, evidence_map)
            res_hash = self._hash_resolution(entity_type, match_keys, canonical.id, [m.id for m in members])

            resolved = None
            if not dry_run:
                resolved = await self.repo.upsert_resolved_entity(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    entity_type=entity_type,
                    canonical_entity_id=canonical.id,
                    match_keys=match_keys,
                    reason_codes=reason_codes,
                    evidence_source_document_ids=evidence_ids,
                    resolution_hash=res_hash,
                )
            summary["resolved_groups"] += 0 if res_hash in existing_resolved_hashes else 1

            for member in members:
                if member.id == canonical.id:
                    continue
                link_match_keys = {**match_keys, "canonical_id": str(canonical.id), "duplicate_id": str(member.id)}
                link_evidence = self._collect_evidence_ids([canonical, member], evidence_map)
                link_hash = self._hash_resolution(
                    entity_type,
                    link_match_keys,
                    canonical.id,
                    [member.id],
                )

                if dry_run:
                    continue

                link = await self.repo.upsert_entity_merge_link(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    entity_type=entity_type,
                    resolved_entity_id=resolved.id if resolved else None,
                    canonical_entity_id=canonical.id,
                    duplicate_entity_id=member.id,
                    match_keys=link_match_keys,
                    reason_codes=reason_codes,
                    evidence_source_document_ids=link_evidence,
                    resolution_hash=link_hash,
                )
                if (link.canonical_entity_id, link.duplicate_entity_id) in existing_link_pairs:
                    summary["merge_links_existing"] += 1
                else:
                    summary["merge_links_written"] += 1

        return summary

    async def list_resolved_entities(self, tenant_id: str, run_id: UUID, entity_type: str | None = None) -> List:
        return await self.repo.list_resolved_entities_for_run(tenant_id, run_id, entity_type=entity_type)

    async def list_entity_merge_links(self, tenant_id: str, run_id: UUID, entity_type: str | None = None) -> List:
        return await self.repo.list_entity_merge_links_for_run(tenant_id, run_id, entity_type=entity_type)

    def _group_executives(self, executives: List[ExecutiveProspect]) -> Dict[Tuple[str, str, str], List[ExecutiveProspect]]:
        grouped: Dict[Tuple[str, str, str], List[ExecutiveProspect]] = {}
        for exec_row in executives:
            key = self._build_match_key(exec_row)
            if not key:
                continue
            grouped.setdefault(key, []).append(exec_row)
        return grouped

    def _build_match_key(self, exec_row: ExecutiveProspect) -> Tuple[str, str, str] | None:
        email_norm = self._normalize_email(exec_row.email)
        name_norm = self._normalize_person(exec_row.name_normalized or exec_row.name_raw)
        company_key = str(exec_row.company_prospect_id)

        if email_norm:
            return ("email", email_norm, company_key)
        if name_norm and company_key:
            return ("name_company", name_norm, company_key)
        return None

    def _match_keys_for_key(self, key: Tuple[str, str, str]) -> Dict[str, Any]:
        match_type, value, company_key = key
        payload = {"match_type": match_type, "match_value": value, "company_prospect_id": company_key}
        return payload

    def _reason_codes_for_key(self, key: Tuple[str, str, str]) -> List[str]:
        match_type, _, _ = key
        if match_type == "email":
            return ["MATCH_EMAIL", "STAGE6_1_RESOLUTION"]
        return ["MATCH_NAME_AND_COMPANY", "STAGE6_1_RESOLUTION"]

    def _canonical_sort_key(self, exec_row: ExecutiveProspect) -> Tuple[datetime, str]:
        created = exec_row.created_at or datetime.max
        return (created, str(exec_row.id))

    def _collect_evidence_ids(
        self,
        exec_rows: Iterable[ExecutiveProspect],
        evidence_map: Dict[UUID, List[UUID]],
    ) -> List[str]:
        collected: set[str] = set()
        for exec_row in exec_rows:
            if exec_row.source_document_id:
                collected.add(str(exec_row.source_document_id))
            for ev_id in evidence_map.get(exec_row.id, []):
                collected.add(str(ev_id))
        return sorted(collected)

    def _build_evidence_map(self, evidence_rows: List[ExecutiveProspectEvidence]) -> Dict[UUID, List[UUID]]:
        mapping: Dict[UUID, List[UUID]] = {}
        for ev in evidence_rows:
            if not ev.source_document_id:
                continue
            mapping.setdefault(ev.executive_prospect_id, []).append(ev.source_document_id)
        return mapping

    def _normalize_person(self, name: str | None) -> str:
        if not name:
            return ""
        lowered = name.lower()
        cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
        return " ".join(cleaned.split())

    def _normalize_email(self, email: str | None) -> str:
        if not email:
            return ""
        return email.strip().lower()

    def _hash_resolution(self, entity_type: str, match_keys: dict, canonical_id: UUID, member_ids: List[UUID]) -> str:
        ordered_members = sorted(str(mid) for mid in member_ids)
        payload = f"{entity_type}|{canonical_id}|{match_keys}|{ordered_members}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

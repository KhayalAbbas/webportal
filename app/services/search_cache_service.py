"""Service helpers for tenant-scoped search result caching."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tenant_search_cache import TenantSearchCache
from app.repositories.search_cache_repository import SearchCacheRepository
from app.repositories.source_document_repository import SourceDocumentRepository
from app.schemas.llm_discovery import LlmDiscoveryPayload
from app.schemas.source_document import SourceDocumentCreate


class SearchCacheService:
    """Cache lookup/persist helpers for discovery providers."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache_repo = SearchCacheRepository(db)
        self.doc_repo = SourceDocumentRepository(db)

    @staticmethod
    def build_cache_key(provider: str, canonical_params: dict[str, Any]) -> tuple[str, str, str]:
        """Return cache_key, request_hash, canonical_json."""
        canonical_json = json.dumps(canonical_params, sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        cache_key = f"{provider}:{request_hash}"
        return cache_key, request_hash, canonical_json

    async def get_cache_hit(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        cache_key: str,
    ) -> Optional[dict[str, Any]]:
        row = await self.cache_repo.get_by_cache_key(tenant_id, provider, cache_key)
        now = datetime.now(timezone.utc)
        if not row or row.expires_at <= now:
            return None

        doc = row.source_document
        if not doc or not doc.text_content:
            return None

        try:
            payload = LlmDiscoveryPayload.model_validate_json(doc.text_content)
        except Exception:  # noqa: BLE001
            return None

        meta = doc.doc_metadata or {}
        return {
            "payload": payload,
            "envelope": meta.get("envelope"),
            "raw_input_meta": meta.get("raw_input_meta"),
            "content_hash": doc.content_hash,
            "source_document_id": str(doc.id),
            "cache_row": row,
        }

    async def store_cache_entry(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        cache_key: str,
        request_hash: str,
        canonical_params: dict[str, Any],
        payload: LlmDiscoveryPayload,
        envelope: Optional[dict[str, Any]],
        raw_input_meta: Optional[dict[str, Any]],
        ttl_seconds: int,
    ) -> TenantSearchCache:
        canonical_payload = payload.canonical_dict()
        payload_text = json.dumps(canonical_payload, sort_keys=True)
        content_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()

        event_id = await self._ensure_research_event(tenant_id, provider)
        doc = await self.doc_repo.create(
            tenant_id,
            SourceDocumentCreate(
                tenant_id=tenant_id,
                research_event_id=event_id,
                document_type="search_cache",
                title=f"Cached search: {provider}",
                url=None,
                storage_path=None,
                text_content=payload_text,
                doc_metadata={
                    "kind": "search_cache",
                    "provider": provider,
                    "cache_key": cache_key,
                    "canonical_params": canonical_params,
                    "envelope": envelope,
                    "raw_input_meta": raw_input_meta,
                    "request_hash": request_hash,
                },
                content_hash=content_hash,
            ),
        )

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, ttl_seconds))
        return await self.cache_repo.upsert_entry(
            tenant_id=tenant_id,
            provider=provider,
            cache_key=cache_key,
            request_hash=request_hash,
            canonical_params=canonical_params,
            source_document_id=doc.id,
            expires_at=expires_at,
            status="ready",
            content_hash=content_hash,
        )

    async def _ensure_research_event(self, tenant_id: UUID, provider: str) -> UUID:
        """Create a lightweight research_event for cache documents."""
        from app.models.research_event import ResearchEvent  # local import to avoid cycle

        event = ResearchEvent(
            tenant_id=tenant_id,
            source_type="SEARCH_PROVIDER",
            source_url=None,
            entity_type="TENANT",
            entity_id=tenant_id,
            raw_payload={"provider": provider, "purpose": "search_cache"},
        )
        self.db.add(event)
        await self.db.flush()
        return event.id

    async def delete_expired(self) -> int:
        return await self.cache_repo.delete_expired(now=datetime.now(timezone.utc))

    @staticmethod
    def default_ttl_seconds() -> int:
        return int(settings.ATS_SEARCH_CACHE_TTL_SECONDS or 604800)

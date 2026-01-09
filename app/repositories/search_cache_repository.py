"""Repository for tenant search cache operations."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_search_cache import TenantSearchCache


class SearchCacheRepository:
    """CRUD helpers for TenantSearchCache."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_cache_key(self, tenant_id: UUID, provider: str, cache_key: str) -> Optional[TenantSearchCache]:
        result = await self.db.execute(
            select(TenantSearchCache).where(
                and_(
                    TenantSearchCache.tenant_id == tenant_id,
                    TenantSearchCache.provider == provider,
                    TenantSearchCache.cache_key == cache_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_entry(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        cache_key: str,
        request_hash: str,
        canonical_params: dict,
        source_document_id: UUID | None,
        expires_at: datetime,
        status: str,
        content_hash: str | None,
    ) -> TenantSearchCache:
        stmt = (
            insert(TenantSearchCache)
            .values(
                tenant_id=tenant_id,
                provider=provider,
                cache_key=cache_key,
                request_hash=request_hash,
                canonical_params=canonical_params,
                source_document_id=source_document_id,
                expires_at=expires_at,
                status=status,
                content_hash=content_hash,
            )
            .on_conflict_do_update(
                index_elements=[TenantSearchCache.tenant_id, TenantSearchCache.provider, TenantSearchCache.cache_key],
                set_={
                    "request_hash": request_hash,
                    "canonical_params": canonical_params,
                    "source_document_id": source_document_id,
                    "expires_at": expires_at,
                    "status": status,
                    "content_hash": content_hash,
                    "updated_at": func.now(),
                },
            )
            .returning(TenantSearchCache)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        row = result.scalar_one()
        return row

    async def delete_expired(self, *, now: datetime) -> int:
        stmt = delete(TenantSearchCache).where(TenantSearchCache.expires_at < now)
        result = await self.db.execute(stmt)
        return int(result.rowcount or 0)

    async def delete_by_provider(self, *, tenant_id: UUID, provider: str) -> int:
        stmt = delete(TenantSearchCache).where(
            and_(TenantSearchCache.tenant_id == tenant_id, TenantSearchCache.provider == provider)
        )
        result = await self.db.execute(stmt)
        return int(result.rowcount or 0)

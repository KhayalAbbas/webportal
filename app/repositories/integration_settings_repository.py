"""Repository for tenant integration secrets and configs."""

from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_integration import TenantIntegrationSecret, TenantIntegrationConfig


class IntegrationSettingsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_secret(self, tenant_id: UUID, provider: str, secret_name: str) -> Optional[TenantIntegrationSecret]:
        result = await self.db.execute(
            select(TenantIntegrationSecret).where(
                and_(
                    TenantIntegrationSecret.tenant_id == tenant_id,
                    TenantIntegrationSecret.provider == provider,
                    TenantIntegrationSecret.secret_name == secret_name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_secret(
        self,
        tenant_id: UUID,
        provider: str,
        secret_name: str,
        ciphertext: str,
        key_version: int,
        last4: Optional[str],
    ) -> TenantIntegrationSecret:
        existing = await self.get_secret(tenant_id, provider, secret_name)
        if existing:
            existing.ciphertext = ciphertext
            existing.key_version = key_version
            existing.last4 = last4
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        record = TenantIntegrationSecret(
            tenant_id=tenant_id,
            provider=provider,
            secret_name=secret_name,
            ciphertext=ciphertext,
            key_version=key_version,
            last4=last4,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_config(self, tenant_id: UUID, provider: str) -> Optional[TenantIntegrationConfig]:
        result = await self.db.execute(
            select(TenantIntegrationConfig).where(
                and_(
                    TenantIntegrationConfig.tenant_id == tenant_id,
                    TenantIntegrationConfig.provider == provider,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_config(self, tenant_id: UUID, provider: str, config_json: dict | None) -> TenantIntegrationConfig:
        existing = await self.get_config(tenant_id, provider)
        if existing:
            existing.config_json = config_json
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        record = TenantIntegrationConfig(
            tenant_id=tenant_id,
            provider=provider,
            config_json=config_json,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def delete_secret(self, tenant_id: UUID, provider: str, secret_name: str) -> None:
        existing = await self.get_secret(tenant_id, provider, secret_name)
        if existing:
            await self.db.delete(existing)
            await self.db.flush()

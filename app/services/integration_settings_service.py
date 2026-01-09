"""Integration settings service for tenant-scoped secrets and configs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.errors import raise_app_error
from app.models.activity_log import ActivityLog
from app.models.ai_enrichment_record import AIEnrichmentRecord
from app.models.research_event import ResearchEvent
from app.models.source_document import SourceDocument
from app.repositories.integration_settings_repository import IntegrationSettingsRepository
from app.services.discovery_provider import ExternalProviderConfigError, get_discovery_provider
from app.services.secrets_service import SecretsService, require_master_key

ProviderConfig = dict[str, Any]


class IntegrationSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = IntegrationSettingsRepository(db)
        self._secrets_service: Optional[SecretsService] = None

    # ------------------------------------------------------------------
    # Secrets helpers
    # ------------------------------------------------------------------
    def _secrets(self) -> SecretsService:
        if self._secrets_service is None:
            self._secrets_service = SecretsService()
        return self._secrets_service

    async def upsert_secret(self, tenant_id: UUID, provider: str, secret_name: str, plaintext: str) -> None:
        if not plaintext:
            raise_app_error(status.HTTP_400_BAD_REQUEST, "SECRET_EMPTY", "Secret value is required")
        service = self._secrets()
        ciphertext, key_version, last4 = service.encrypt(plaintext)
        await self.repo.upsert_secret(
            tenant_id=tenant_id,
            provider=provider,
            secret_name=secret_name,
            ciphertext=ciphertext,
            key_version=key_version,
            last4=last4,
        )

    async def _decrypt_secret(self, ciphertext: str) -> str:
        service = self._secrets()
        return service.decrypt(ciphertext)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    async def upsert_config(self, tenant_id: UUID, provider: str, config_json: dict[str, Any] | None) -> None:
        await self.repo.upsert_config(tenant_id=tenant_id, provider=provider, config_json=config_json)

    async def get_public_state(self, tenant_id: UUID) -> dict[str, dict[str, Any]]:
        xai_secret = await self.repo.get_secret(tenant_id, "xai_grok", "api_key")
        google_secret = await self.repo.get_secret(tenant_id, "google_cse", "api_key")

        xai_config = await self.repo.get_config(tenant_id, "xai_grok")
        google_config = await self.repo.get_config(tenant_id, "google_cse")

        return {
            "xai_grok": {
                "configured": bool(xai_secret or settings.XAI_API_KEY),
                "last4": xai_secret.last4 if xai_secret else None,
                "updated_at": xai_secret.updated_at if xai_secret else None,
                "has_env_fallback": bool(settings.XAI_API_KEY),
                "config": (xai_config.config_json if xai_config else {}) or {},
            },
            "google_cse": {
                "configured": bool(google_secret or settings.GOOGLE_CSE_API_KEY),
                "last4": google_secret.last4 if google_secret else None,
                "updated_at": google_secret.updated_at if google_secret else None,
                "has_env_fallback": bool(settings.GOOGLE_CSE_API_KEY),
                "config": (google_config.config_json if google_config else {}) or {},
            },
        }

    async def resolve_runtime_config(self, tenant_id: UUID, provider: str, require_secret: bool = False) -> ProviderConfig:
        secret_row = await self.repo.get_secret(tenant_id, provider, "api_key")
        secret_plain = None
        if secret_row:
            require_master_key()
            secret_plain = await self._decrypt_secret(secret_row.ciphertext)

        config_row = await self.repo.get_config(tenant_id, provider)
        config_json = (config_row.config_json if config_row else {}) or {}

        if provider == "xai_grok":
            api_key = secret_plain or settings.XAI_API_KEY
            model_name = config_json.get("model") or settings.XAI_MODEL or "grok-2"
            if require_secret and not api_key:
                raise_app_error(status.HTTP_400_BAD_REQUEST, "INTEGRATION_SECRET_MISSING", "xAI API key is not configured")
            return {"api_key": api_key, "model": model_name}

        if provider == "google_cse":
            api_key = secret_plain or settings.GOOGLE_CSE_API_KEY
            cx = config_json.get("cx") or settings.GOOGLE_CSE_CX
            if require_secret and not api_key:
                raise_app_error(status.HTTP_400_BAD_REQUEST, "INTEGRATION_SECRET_MISSING", "Google CSE API key is not configured")
            if require_secret and not cx:
                raise_app_error(status.HTTP_400_BAD_REQUEST, "INTEGRATION_CONFIG_MISSING", "Google CSE CX is not configured")
            return {"api_key": api_key, "cx": cx}

        return {}

    # ------------------------------------------------------------------
    # Activity / evidence helpers
    # ------------------------------------------------------------------
    async def _log_activity(self, tenant_id: UUID, message: str, actor: str | None = None) -> None:
        entry = ActivityLog(
            tenant_id=tenant_id,
            type="INTEGRATION",
            message=message,
            created_by=actor,
        )
        self.db.add(entry)
        await self.db.flush()

    async def _record_evidence(self, tenant_id: UUID, provider: str, outcome: str, envelope: dict[str, Any], actor: str | None = None) -> None:
        event = ResearchEvent(
            tenant_id=tenant_id,
            source_type="INTEGRATION_TEST",
            source_url=None,
            entity_type="TENANT",
            entity_id=tenant_id,
            raw_payload={"provider": provider, "outcome": outcome},
        )
        self.db.add(event)
        await self.db.flush()

        document = SourceDocument(
            tenant_id=tenant_id,
            research_event_id=event.id,
            document_type="provider_json",
            title=f"Integration test: {provider}",
            url=None,
            storage_path=None,
            text_content=json.dumps(envelope, sort_keys=True, indent=2),
            doc_metadata={"kind": "integration_test", "provider": provider},
        )
        self.db.add(document)
        await self.db.flush()

        enrichment = AIEnrichmentRecord(
            tenant_id=tenant_id,
            target_type="TENANT",
            target_id=tenant_id,
            model_name="integration_test_v1",
            enrichment_type="integration_test",
            payload={"provider": provider, "outcome": outcome},
            purpose="integration_test",
            provider=provider,
            source_document_id=None,
            status="success" if outcome == "PASS" else "error",
        )
        self.db.add(enrichment)
        await self.db.flush()

        await self._log_activity(tenant_id, f"Integration test run: provider={provider} result={outcome}", actor)

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    async def save_provider_settings(
        self,
        tenant_id: UUID,
        provider: str,
        api_key: Optional[str],
        config_json: Optional[dict[str, Any]],
        actor: Optional[str],
    ) -> None:
        if api_key:
            require_master_key()
            await self.upsert_secret(tenant_id, provider, "api_key", api_key)
        if config_json is not None:
            await self.upsert_config(tenant_id, provider, config_json)
        await self._log_activity(tenant_id, f"Integration settings updated for {provider}", actor)

    async def test_provider(self, tenant_id: UUID, provider: str, actor: Optional[str]) -> dict[str, Any]:
        runtime_config = await self.resolve_runtime_config(tenant_id, provider, require_secret=True)
        provider_obj = get_discovery_provider(provider)
        if not provider_obj:
            raise_app_error(status.HTTP_404_NOT_FOUND, "PROVIDER_NOT_FOUND", f"Provider {provider} is not registered")

        run_id = uuid4()
        request_payload: dict[str, Any]
        if provider == "xai_grok":
            request_payload = {"query": "integration test", "max_companies": 1, "notes": "connectivity"}
        elif provider == "google_cse":
            request_payload = {"query": "integration connectivity", "num_results": 1}
        else:
            request_payload = {}

        try:
            result = provider_obj.run(
                tenant_id=str(tenant_id),
                run_id=run_id,
                request=request_payload,
                runtime_config=runtime_config,
            )
        except ExternalProviderConfigError as exc:
            await self._record_evidence(
                tenant_id,
                provider,
                "FAIL",
                {"provider": provider, "error": exc.details or {"message": str(exc)}},
                actor,
            )
            return {"status": "fail", "error": str(exc)}

        outcome = "PASS" if not result.error else "FAIL"
        envelope = {
            "provider": provider,
            "runtime_config_used": {k: v for k, v in runtime_config.items() if k not in {"api_key"}},
            "request": request_payload,
            "envelope": result.envelope,
            "error": result.error,
            "model": result.model,
        }
        await self._record_evidence(tenant_id, provider, outcome, envelope, actor)
        return {"status": outcome.lower(), "error": result.error}

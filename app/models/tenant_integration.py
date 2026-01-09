"""
Tenant integration secrets and configs.
"""

from typing import Optional

from sqlalchemy import String, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import TenantScopedModel


class TenantIntegrationSecret(TenantScopedModel):
    """Encrypted tenant-scoped provider secrets."""

    __tablename__ = "tenant_integration_secrets"

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    secret_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last4: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "secret_name", name="uq_tenant_integration_secret"),
    )


class TenantIntegrationConfig(TenantScopedModel):
    """Non-secret provider configuration per tenant (e.g., model, CX)."""

    __tablename__ = "tenant_integration_configs"

    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    config_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_tenant_integration_config"),
    )

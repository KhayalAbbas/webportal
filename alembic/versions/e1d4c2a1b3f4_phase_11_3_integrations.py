"""Phase 11.3: tenant integration secrets and configs

Revision ID: e1d4c2a1b3f4
Revises: b6f20f1d5a7c
Create Date: 2026-01-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e1d4c2a1b3f4"
down_revision = "b6f20f1d5a7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_integration_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("secret_name", sa.String(length=100), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last4", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", "secret_name", name="uq_tenant_integration_secret"),
    )
    op.create_index(
        "ix_tenant_integration_secrets_tenant_provider",
        "tenant_integration_secrets",
        ["tenant_id", "provider"],
    )

    op.create_table(
        "tenant_integration_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_tenant_integration_config"),
    )
    op.create_index(
        "ix_tenant_integration_configs_tenant_provider",
        "tenant_integration_configs",
        ["tenant_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_integration_configs_tenant_provider", table_name="tenant_integration_configs")
    op.drop_table("tenant_integration_configs")
    op.drop_index("ix_tenant_integration_secrets_tenant_provider", table_name="tenant_integration_secrets")
    op.drop_table("tenant_integration_secrets")

"""Add robots policy cache table

Revision ID: 7f3e9b5e2d9b
Revises: 72d5c1b8d3e3
Create Date: 2026-01-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7f3e9b5e2d9b"
down_revision: Union[str, None] = "72d5c1b8d3e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "robots_policy_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("origin", sa.String(length=50), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "domain", "user_agent", name="uq_robots_policy_cache"),
    )
    op.create_index("ix_robots_policy_cache_tenant_id", "robots_policy_cache", ["tenant_id"], unique=False)
    op.create_index("ix_robots_policy_cache_domain_user_agent", "robots_policy_cache", ["domain", "user_agent"], unique=False)
    op.create_index("ix_robots_policy_cache_expires_at", "robots_policy_cache", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_robots_policy_cache_expires_at", table_name="robots_policy_cache")
    op.drop_index("ix_robots_policy_cache_domain_user_agent", table_name="robots_policy_cache")
    op.drop_index("ix_robots_policy_cache_tenant_id", table_name="robots_policy_cache")
    op.drop_table("robots_policy_cache")

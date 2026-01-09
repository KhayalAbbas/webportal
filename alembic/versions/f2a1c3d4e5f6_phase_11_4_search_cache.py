"""Phase 11.4: search cache + content hashes

Revision ID: f2a1c3d4e5f6
Revises: e1d4c2a1b3f4
Create Date: 2026-01-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f2a1c3d4e5f6"
down_revision: Union[str, None] = "e1d4c2a1b3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_document", sa.Column("content_hash", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_source_document_tenant_content_hash",
        "source_document",
        ["tenant_id", "content_hash"],
        unique=False,
    )

    op.create_table(
        "tenant_search_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("canonical_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_document.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", "cache_key", name="uq_search_cache_key"),
    )
    op.create_index("ix_search_cache_expires", "tenant_search_cache", ["expires_at"], unique=False)
    op.create_index(
        "ix_search_cache_request_hash",
        "tenant_search_cache",
        ["tenant_id", "provider", "request_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_search_cache_request_hash", table_name="tenant_search_cache")
    op.drop_index("ix_search_cache_expires", table_name="tenant_search_cache")
    op.drop_table("tenant_search_cache")
    op.drop_index("ix_source_document_tenant_content_hash", table_name="source_document")
    op.drop_column("source_document", "content_hash")

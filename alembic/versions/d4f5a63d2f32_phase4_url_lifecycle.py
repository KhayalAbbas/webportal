"""Phase 4 URL lifecycle and idempotency fields

Revision ID: d4f5a63d2f32
Revises: c7f2c2a1c4b4
Create Date: 2026-01-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4f5a63d2f32"
down_revision: Union[str, None] = "c7f2c2a1c4b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lifecycle fields
    op.add_column(
        "source_documents",
        sa.Column("url_normalized", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "source_documents",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    # Normalize existing data to the new lifecycle
    op.execute("""
        UPDATE source_documents
        SET status = 'queued'
        WHERE status = 'new' AND source_type = 'url'
    """)

    op.execute(
        """
        UPDATE source_documents
        SET url_normalized = url
        WHERE url_normalized IS NULL AND url IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE source_documents
        SET attempt_count = 0
        WHERE attempt_count IS NULL
        """
    )

    op.execute(
        """
        UPDATE source_documents
        SET last_error = error_message
        WHERE last_error IS NULL AND error_message IS NOT NULL
        """
    )

    # Update default for future inserts
    op.alter_column(
        "source_documents",
        "status",
        existing_type=sa.String(length=50),
        server_default=sa.text("'queued'"),
        existing_nullable=False,
    )

    # Partial unique index for idempotent URL fetch
    op.create_index(
        "uq_source_docs_run_url_hash",
        "source_documents",
        ["tenant_id", "company_research_run_id", "url_normalized", "content_hash"],
        unique=True,
        postgresql_where=sa.text("url_normalized IS NOT NULL AND content_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_source_docs_run_url_hash", table_name="source_documents")
    op.alter_column(
        "source_documents",
        "status",
        existing_type=sa.String(length=50),
        server_default=None,
        existing_nullable=False,
    )
    op.drop_column("source_documents", "last_error")
    op.drop_column("source_documents", "next_retry_at")
    op.drop_column("source_documents", "attempt_count")
    op.drop_column("source_documents", "url_normalized")

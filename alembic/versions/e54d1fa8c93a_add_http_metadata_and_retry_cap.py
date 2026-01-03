"""Add HTTP metadata and retry cap to source documents

Revision ID: e54d1fa8c93a
Revises: d4f5a63d2f32
Create Date: 2026-01-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e54d1fa8c93a"
down_revision: Union[str, None] = "d4f5a63d2f32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
    )
    op.add_column(
        "source_documents",
        sa.Column("http_status_code", sa.Integer(), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("http_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("http_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_documents",
        sa.Column("http_final_url", sa.Text(), nullable=True),
    )

    # Normalize null max_attempts for existing rows
    op.execute("UPDATE source_documents SET max_attempts = 3 WHERE max_attempts IS NULL")


def downgrade() -> None:
    op.drop_column("source_documents", "http_final_url")
    op.drop_column("source_documents", "http_error_message")
    op.drop_column("source_documents", "http_headers")
    op.drop_column("source_documents", "http_status_code")
    op.drop_column("source_documents", "max_attempts")

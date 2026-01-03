"""Add canonical URL tracking and dedupe linkage

Revision ID: 72d5c1b8d3e3
Revises: 0d021d1c7755
Create Date: 2026-01-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "72d5c1b8d3e3"
down_revision: Union[str, None] = "0d021d1c7755"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_documents", sa.Column("original_url", sa.Text(), nullable=True))
    op.add_column("source_documents", sa.Column("canonical_final_url", sa.Text(), nullable=True))
    op.add_column(
        "source_documents",
        sa.Column("canonical_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_source_documents_canonical_source",
        "source_documents",
        "source_documents",
        ["canonical_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_source_documents_canonical_source_id",
        "source_documents",
        ["canonical_source_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE source_documents
        SET original_url = url
        WHERE original_url IS NULL AND url IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE source_documents
        SET canonical_source_id = id
        WHERE canonical_source_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE source_documents
        SET canonical_final_url = http_final_url
        WHERE canonical_final_url IS NULL AND http_final_url IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_source_documents_canonical_source_id", table_name="source_documents")
    op.drop_constraint("fk_source_documents_canonical_source", "source_documents", type_="foreignkey")
    op.drop_column("source_documents", "canonical_source_id")
    op.drop_column("source_documents", "canonical_final_url")
    op.drop_column("source_documents", "original_url")

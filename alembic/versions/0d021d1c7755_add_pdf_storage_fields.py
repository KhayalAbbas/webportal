"""Add PDF storage fields to source documents

Revision ID: 0d021d1c7755
Revises: e54d1fa8c93a
Create Date: 2026-01-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0d021d1c7755"
down_revision: Union[str, None] = "e54d1fa8c93a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_documents", sa.Column("file_name", sa.String(length=255), nullable=True))
    op.add_column("source_documents", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))
    op.add_column("source_documents", sa.Column("content_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_documents", "content_size")
    op.drop_column("source_documents", "content_bytes")
    op.drop_column("source_documents", "file_name")

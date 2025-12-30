"""Add manual list partial unique index

Revision ID: 2b2f8443931b
Revises: 31741119f462
Create Date: 2025-12-31 12:00:00.000000

Adds a partial unique index to make manual_list evidence idempotent when
source_document_id and source_url are absent. The index deduplicates per
prospect/source while allowing other evidence types to continue using their
existing constraints.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2b2f8443931b"
down_revision: Union[str, None] = "31741119f462"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create manual_list partial unique index."""
    op.execute(
        """
        CREATE UNIQUE INDEX uq_cpe_manual_list_idempotent
        ON company_prospect_evidence (tenant_id, company_prospect_id, source_type, source_name)
        WHERE source_type = 'manual_list' AND source_document_id IS NULL AND source_url IS NULL
        """
    )


def downgrade() -> None:
    """Drop manual_list partial unique index."""
    op.execute("DROP INDEX IF EXISTS uq_cpe_manual_list_idempotent")

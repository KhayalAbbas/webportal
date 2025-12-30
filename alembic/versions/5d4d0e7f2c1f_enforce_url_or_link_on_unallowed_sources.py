"""Enforce URL or document on disallowed source types

Revision ID: 5d4d0e7f2c1f
Revises: 2b2f8443931b
Create Date: 2025-12-31 15:00:00.000000

Adds a check constraint so that non-manual evidence must have either a URL or
linked source_document unless its source_type is explicitly allowed to be
URL-less.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5d4d0e7f2c1f"
down_revision: Union[str, None] = "2b2f8443931b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALLOWED_URL_LESS = ("manual_list", "ai_proposal_company", "ai_proposal_metric", "document")


def upgrade() -> None:
    """Add check constraint enforcing URL or source_document for disallowed types."""
    allowed_list = ", ".join(f"'{t}'" for t in ALLOWED_URL_LESS)
    op.execute(
        f"""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_cpe_url_or_doc_for_disallowed_types
        CHECK (
            source_type = ANY (ARRAY[{allowed_list}])
            OR source_url IS NOT NULL
            OR source_document_id IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    """Drop check constraint."""
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT IF EXISTS chk_cpe_url_or_doc_for_disallowed_types")

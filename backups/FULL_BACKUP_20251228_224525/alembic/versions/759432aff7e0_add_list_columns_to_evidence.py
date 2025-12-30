"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '759432aff7e0'
down_revision: Union[str, None] = '1fb8cbb17dad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - add list columns to evidence table."""
    op.add_column('company_prospect_evidence',
        sa.Column('list_name', sa.String(500), nullable=True))
    op.add_column('company_prospect_evidence',
        sa.Column('list_rank_position', sa.Integer, nullable=True))
    op.add_column('company_prospect_evidence',
        sa.Column('search_query_used', sa.Text, nullable=True))


def downgrade() -> None:
    """Reverse the migration - drop list columns."""
    op.drop_column('company_prospect_evidence', 'search_query_used')
    op.drop_column('company_prospect_evidence', 'list_rank_position')
    op.drop_column('company_prospect_evidence', 'list_name')

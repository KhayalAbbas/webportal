"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ffc71e328d0'
down_revision: Union[str, None] = 'f3a5e6ddee21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - create tables, add columns, etc."""
    # Make company_research_run_id nullable in source_documents table
    op.alter_column('source_documents', 'company_research_run_id',
                   existing_type=sa.UUID(),
                   nullable=True)


def downgrade() -> None:
    """Reverse the migration - drop tables, remove columns, etc."""
    # Make company_research_run_id NOT NULL again
    op.alter_column('source_documents', 'company_research_run_id',
                   existing_type=sa.UUID(),
                   nullable=False)

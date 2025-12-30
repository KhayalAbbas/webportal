"""add_retry_at_to_research_jobs

Add retry_at column to research_jobs table for better job retry semantics.

Revision ID: c06d212c49af
Revises: dd32464b5290
Create Date: 2025-12-29 12:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c06d212c49af'
down_revision: Union[str, None] = 'dd32464b5290'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - add retry_at column."""
    op.add_column('research_jobs', sa.Column('retry_at', postgresql.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    """Reverse the migration - remove retry_at column."""
    op.drop_column('research_jobs', 'retry_at')

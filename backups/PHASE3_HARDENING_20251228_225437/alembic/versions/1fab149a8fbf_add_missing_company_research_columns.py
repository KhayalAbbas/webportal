"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fab149a8fbf'
down_revision: Union[str, None] = 'b2d69e5ebcc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing columns to company_research_runs table."""
    # Add sector column (required)
    op.add_column('company_research_runs', 
        sa.Column('sector', sa.String(length=100), nullable=True)  # nullable first
    )
    
    # Add region_scope column (JSONB, optional)
    op.add_column('company_research_runs',
        sa.Column('region_scope', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    
    # Add summary column (optional)
    op.add_column('company_research_runs',
        sa.Column('summary', sa.Text(), nullable=True)
    )
    
    # Add error_message column (optional)
    op.add_column('company_research_runs',
        sa.Column('error_message', sa.Text(), nullable=True)
    )
    
    # Add started_at column (optional)
    op.add_column('company_research_runs',
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    # Add finished_at column (optional)
    op.add_column('company_research_runs',
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    # Now make sector NOT NULL after adding it
    # (Safe because table is currently empty)
    op.alter_column('company_research_runs', 'sector',
        existing_type=sa.String(length=100),
        nullable=False
    )


def downgrade() -> None:
    """Remove the added columns."""
    op.drop_column('company_research_runs', 'finished_at')
    op.drop_column('company_research_runs', 'started_at')
    op.drop_column('company_research_runs', 'error_message')
    op.drop_column('company_research_runs', 'summary')
    op.drop_column('company_research_runs', 'region_scope')
    op.drop_column('company_research_runs', 'sector')

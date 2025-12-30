"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d69e5ebcc3'
down_revision: Union[str, None] = '005_company_research'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - rename tables to match model plural naming."""
    # Rename tables from singular to plural to match SQLAlchemy models
    op.rename_table('company_research_run', 'company_research_runs')
    op.rename_table('company_prospect', 'company_prospects')
    op.rename_table('company_prospect_metric', 'company_prospect_metrics')
    # company_prospect_evidence stays singular (matches model)


def downgrade() -> None:
    """Reverse the migration - revert table names back to singular."""
    op.rename_table('company_research_runs', 'company_research_run')
    op.rename_table('company_prospects', 'company_prospect')
    op.rename_table('company_prospect_metrics', 'company_prospect_metric')

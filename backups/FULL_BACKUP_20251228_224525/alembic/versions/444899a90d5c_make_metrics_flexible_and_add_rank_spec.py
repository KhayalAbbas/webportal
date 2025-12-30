"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '444899a90d5c'
down_revision: Union[str, None] = '2fc6e8612026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - make metrics flexible with typed values and add rank_spec."""
    
    # 1. Add value_type column to company_metrics
    op.add_column('company_metrics', sa.Column('value_type', sa.String(20), nullable=True))
    
    # 2. Add value_bool column to company_metrics
    op.add_column('company_metrics', sa.Column('value_bool', sa.Boolean(), nullable=True))
    
    # 3. Add value_json column to company_metrics
    op.add_column('company_metrics', sa.Column('value_json', sa.dialects.postgresql.JSONB(), nullable=True))
    
    # 4. Add unit column to company_metrics
    op.add_column('company_metrics', sa.Column('unit', sa.String(50), nullable=True))
    
    # 5. Set value_type='number' for existing rows with value_number
    op.execute("""
        UPDATE company_metrics 
        SET value_type = 'number' 
        WHERE value_number IS NOT NULL AND value_type IS NULL
    """)
    
    # 6. Set value_type='text' for existing rows with value_text
    op.execute("""
        UPDATE company_metrics 
        SET value_type = 'text' 
        WHERE value_text IS NOT NULL AND value_type IS NULL
    """)
    
    # 7. Make value_type NOT NULL now that existing rows are populated
    op.alter_column('company_metrics', 'value_type', nullable=False)
    
    # 8. Add rank_spec column to company_research_runs
    op.add_column('company_research_runs', 
                  sa.Column('rank_spec', sa.dialects.postgresql.JSONB(), 
                           nullable=False, server_default='{}'))


def downgrade() -> None:
    """Reverse the migration."""
    
    # Remove rank_spec from company_research_runs
    op.drop_column('company_research_runs', 'rank_spec')
    
    # Remove new columns from company_metrics
    op.drop_column('company_metrics', 'unit')
    op.drop_column('company_metrics', 'value_json')
    op.drop_column('company_metrics', 'value_bool')
    op.drop_column('company_metrics', 'value_type')

"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fc6e8612026'
down_revision: Union[str, None] = '759432aff7e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - create tables, add columns, etc."""
    # Create company_metrics table
    op.create_table(
        'company_metrics',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('company_research_run_id', sa.UUID(), nullable=False),
        sa.Column('company_prospect_id', sa.UUID(), nullable=False),
        sa.Column('metric_key', sa.String(200), nullable=False),
        sa.Column('value_number', sa.Numeric(20, 4), nullable=True),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('value_currency', sa.String(10), nullable=True),
        sa.Column('as_of_date', sa.Date(), nullable=True),
        sa.Column('confidence', sa.Numeric(3, 2), nullable=True),
        sa.Column('source_document_id', sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ),
        sa.ForeignKeyConstraint(['company_research_run_id'], ['company_research_runs.id'], ),
        sa.ForeignKeyConstraint(['company_prospect_id'], ['company_prospects.id'], ),
        sa.ForeignKeyConstraint(['source_document_id'], ['source_documents.id'], ),
    )
    op.create_index('ix_company_metrics_tenant_id', 'company_metrics', ['tenant_id'])
    op.create_index('ix_company_metrics_run_id', 'company_metrics', ['company_research_run_id'])
    op.create_index('ix_company_metrics_prospect_id', 'company_metrics', ['company_prospect_id'])
    op.create_index('ix_company_metrics_key', 'company_metrics', ['metric_key'])
    
    # Create company_aliases table
    op.create_table(
        'company_aliases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('company_prospect_id', sa.UUID(), nullable=False),
        sa.Column('alias_name', sa.String(500), nullable=False),
        sa.Column('alias_type', sa.String(50), nullable=False),  # 'legal', 'trade', 'former', 'local'
        sa.Column('source_type', sa.String(100), nullable=True),
        sa.Column('confidence', sa.Numeric(3, 2), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ),
        sa.ForeignKeyConstraint(['company_prospect_id'], ['company_prospects.id'], ),
    )
    op.create_index('ix_company_aliases_tenant_id', 'company_aliases', ['tenant_id'])
    op.create_index('ix_company_aliases_prospect_id', 'company_aliases', ['company_prospect_id'])
    op.create_index('ix_company_aliases_name', 'company_aliases', ['alias_name'])
    
    # Extend source_documents with AI proposal fields
    op.add_column('source_documents', sa.Column('provider', sa.String(100), nullable=True))
    op.add_column('source_documents', sa.Column('snippet', sa.Text(), nullable=True))
    
    # Add AI ranking fields to company_prospects
    op.add_column('company_prospects', sa.Column('ai_rank', sa.Integer(), nullable=True))
    op.add_column('company_prospects', sa.Column('ai_score', sa.Numeric(5, 4), nullable=True))


def downgrade() -> None:
    """Reverse the migration - drop tables, remove columns, etc."""
    # Remove added columns from company_prospects
    op.drop_column('company_prospects', 'ai_score')
    op.drop_column('company_prospects', 'ai_rank')
    
    # Remove added columns from source_documents
    op.drop_column('source_documents', 'snippet')
    op.drop_column('source_documents', 'provider')
    
    # Drop company_aliases table
    op.drop_index('ix_company_aliases_name', 'company_aliases')
    op.drop_index('ix_company_aliases_prospect_id', 'company_aliases')
    op.drop_index('ix_company_aliases_tenant_id', 'company_aliases')
    op.drop_table('company_aliases')
    
    # Drop company_metrics table
    op.drop_index('ix_company_metrics_key', 'company_metrics')
    op.drop_index('ix_company_metrics_prospect_id', 'company_metrics')
    op.drop_index('ix_company_metrics_run_id', 'company_metrics')
    op.drop_index('ix_company_metrics_tenant_id', 'company_metrics')
    op.drop_table('company_metrics')

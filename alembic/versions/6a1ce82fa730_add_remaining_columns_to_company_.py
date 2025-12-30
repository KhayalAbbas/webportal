"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6a1ce82fa730'
down_revision: Union[str, None] = 'cc2a9a76ca6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align company_prospects columns with model."""
    
    # RENAME existing columns to match model
    op.alter_column('company_prospects', 'website', new_column_name='website_url')
    op.alter_column('company_prospects', 'industry_sector', new_column_name='sector')
    op.alter_column('company_prospects', 'brief_description', new_column_name='description')
    op.alter_column('company_prospects', 'headquarters_location', new_column_name='hq_city')
    op.alter_column('company_prospects', 'country_code', new_column_name='hq_country')
    
    # Change hq_country length from VARCHAR to VARCHAR(2) for ISO codes
    op.alter_column('company_prospects', 'hq_country',
        type_=sa.String(length=2),
        existing_type=sa.String()
    )
    op.alter_column('company_prospects', 'hq_city',
        type_=sa.String(length=200),
        existing_type=sa.String()
    )
    op.alter_column('company_prospects', 'sector',
        type_=sa.String(length=100),
        existing_type=sa.String()
    )
    op.alter_column('company_prospects', 'description',
        type_=sa.Text(),
        existing_type=sa.Text()
    )
    op.alter_column('company_prospects', 'website_url',
        type_=sa.String(length=500),
        existing_type=sa.String()
    )
    
    # ADD new columns that don't exist
    op.add_column('company_prospects',
        sa.Column('subsector', sa.String(length=100), nullable=True)
    )
    
    op.add_column('company_prospects',
        sa.Column('employees_band', sa.String(length=50), nullable=True)
    )
    
    op.add_column('company_prospects',
        sa.Column('revenue_band_usd', sa.String(length=50), nullable=True)
    )
    
    op.add_column('company_prospects',
        sa.Column('countries_of_operation', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    
    op.add_column('company_prospects',
        sa.Column('data_confidence', sa.Numeric(precision=3, scale=2), nullable=False, server_default='0.0')
    )
    
    op.add_column('company_prospects',
        sa.Column('approved_by_user_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    op.add_column('company_prospects',
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    # Foreign key for approved_by
    op.create_foreign_key(
        'fk_company_prospects_approved_by_user_id',
        'company_prospects', 'user',
        ['approved_by_user_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Normalized company ID for deduplication
    op.add_column('company_prospects',
        sa.Column('normalized_company_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index('ix_company_prospects_normalized_company_id', 'company_prospects', ['normalized_company_id'])
    
    # Update relevance_score and evidence_score to NUMERIC(3, 2) instead of FLOAT
    op.alter_column('company_prospects', 'relevance_score',
        type_=sa.Numeric(precision=3, scale=2),
        existing_type=sa.Float(),
        nullable=False,
        server_default='0.0'
    )
    
    op.alter_column('company_prospects', 'evidence_score',
        type_=sa.Numeric(precision=3, scale=2),
        existing_type=sa.Float(),
        nullable=False,
        server_default='0.0'
    )


def downgrade() -> None:
    """Reverse the migration."""
    # Remove server defaults
    op.alter_column('company_prospects', 'relevance_score', server_default=None)
    op.alter_column('company_prospects', 'evidence_score', server_default=None)
    
    # Revert column types
    op.alter_column('company_prospects', 'relevance_score',
        type_=sa.Float(),
        existing_type=sa.Numeric(precision=3, scale=2)
    )
    op.alter_column('company_prospects', 'evidence_score',
        type_=sa.Float(),
        existing_type=sa.Numeric(precision=3, scale=2)
    )
    
    # Remove new columns and indexes
    op.drop_index('ix_company_prospects_normalized_company_id', 'company_prospects')
    op.drop_constraint('fk_company_prospects_approved_by_user_id', 'company_prospects', type_='foreignkey')
    
    op.drop_column('company_prospects', 'normalized_company_id')
    op.drop_column('company_prospects', 'approved_at')
    op.drop_column('company_prospects', 'approved_by_user_id')
    op.drop_column('company_prospects', 'data_confidence')
    op.drop_column('company_prospects', 'countries_of_operation')
    op.drop_column('company_prospects', 'revenue_band_usd')
    op.drop_column('company_prospects', 'employees_band')
    op.drop_column('company_prospects', 'subsector')
    
    # Revert column renames
    op.alter_column('company_prospects', 'hq_country', new_column_name='country_code')
    op.alter_column('company_prospects', 'hq_city', new_column_name='headquarters_location')
    op.alter_column('company_prospects', 'description', new_column_name='brief_description')
    op.alter_column('company_prospects', 'sector', new_column_name='industry_sector')
    op.alter_column('company_prospects', 'website_url', new_column_name='website')

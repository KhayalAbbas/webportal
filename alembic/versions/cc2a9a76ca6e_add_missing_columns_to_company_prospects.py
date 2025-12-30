"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'cc2a9a76ca6e'
down_revision: Union[str, None] = '1fab149a8fbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing columns to company_prospects table."""
    # Add role_mandate_id (denormalized for easy querying)
    op.add_column('company_prospects',
        sa.Column('role_mandate_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # Add index for role_mandate_id
    op.create_index('ix_company_prospects_role_mandate_id', 'company_prospects', ['role_mandate_id'])
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_company_prospects_role_mandate_id',
        'company_prospects', 'role',
        ['role_mandate_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # Add name_raw column (raw company name as discovered)
    op.add_column('company_prospects',
        sa.Column('name_raw', sa.String(length=500), nullable=True)
    )
    
    # Populate name_raw from name_normalized for existing rows (if any)
    op.execute("""
        UPDATE company_prospects 
        SET name_raw = name_normalized 
        WHERE name_raw IS NULL
    """)
    
    # Now make them NOT NULL
    op.alter_column('company_prospects', 'role_mandate_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False
    )
    
    op.alter_column('company_prospects', 'name_raw',
        existing_type=sa.String(length=500),
        nullable=False
    )


def downgrade() -> None:
    """Remove the added columns."""
    op.drop_constraint('fk_company_prospects_role_mandate_id', 'company_prospects', type_='foreignkey')
    op.drop_index('ix_company_prospects_role_mandate_id', 'company_prospects')
    op.drop_column('company_prospects', 'name_raw')
    op.drop_column('company_prospects', 'role_mandate_id')

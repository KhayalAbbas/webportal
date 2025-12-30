"""
Alembic migration script template.

This is used when generating new migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42e42baff25d'
down_revision: Union[str, None] = '6a1ce82fa730'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the old 'name' column - model only uses name_raw and name_normalized."""
    # First, populate name_normalized from name if it's NULL
    op.execute("""
        UPDATE company_prospects 
        SET name_normalized = LOWER(TRIM(name))
        WHERE name_normalized IS NULL AND name IS NOT NULL
    """)
    
    # Make name_normalized NOT NULL now that we've populated it
    op.alter_column('company_prospects', 'name_normalized',
        existing_type=sa.String(),
        nullable=False
    )
    
    # Drop the old 'name' column
    op.drop_column('company_prospects', 'name')


def downgrade() -> None:
    """Re-add the 'name' column if needed."""
    op.add_column('company_prospects',
        sa.Column('name', sa.String(length=255), nullable=False, server_default='')
    )
    
    # Populate from name_raw
    op.execute("""
        UPDATE company_prospects 
        SET name = name_raw
    """)
    
    # Remove server default
    op.alter_column('company_prospects', 'name', server_default=None)

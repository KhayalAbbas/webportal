"""add_user_authentication

Revision ID: 003_add_user_auth
Revises: 002_extended
Create Date: 2024-12-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_add_user_auth'
down_revision: Union[str, None] = '002_extended'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user table and authentication fields."""
    
    # Create user table
    op.create_table(
        'user',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
    )
    
    # Create unique index on (tenant_id, email) - email must be unique per tenant
    op.create_index(
        'ix_user_tenant_email',
        'user',
        ['tenant_id', 'email'],
        unique=True
    )
    
    # Create regular index on tenant_id for faster lookups
    op.create_index('ix_user_tenant_id', 'user', ['tenant_id'])
    
    # Create index on email for faster lookups
    op.create_index('ix_user_email', 'user', ['email'])


def downgrade() -> None:
    """Remove user table and authentication fields."""
    
    # Drop indexes
    op.drop_index('ix_user_email', table_name='user')
    op.drop_index('ix_user_tenant_id', table_name='user')
    op.drop_index('ix_user_tenant_email', table_name='user')
    
    # Drop user table
    op.drop_table('user')

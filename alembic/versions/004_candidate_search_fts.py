"""Add full-text search support for candidates

Revision ID: 004_candidate_search_fts
Revises: 003_add_user_auth
Create Date: 2025-12-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_candidate_search_fts'
down_revision: Union[str, None] = '003_add_user_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add full-text search support for candidates.
    
    Creates:
    1. A generated tsvector column combining searchable text fields
    2. A GIN index on that tsvector column for fast search
    3. A trigger to keep the tsvector column up to date
    """
    
    # Add a tsvector column for full-text search
    op.execute("""
        ALTER TABLE candidate
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(first_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(last_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(current_title, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(current_company, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(bio, '')), 'C') ||
            setweight(to_tsvector('english', coalesce(tags, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(cv_text, '')), 'D')
        ) STORED;
    """)
    
    # Create a GIN index on the tsvector column for fast full-text search
    op.create_index(
        'idx_candidate_search_vector',
        'candidate',
        ['search_vector'],
        postgresql_using='gin'
    )
    
    # Create additional indexes for common filter fields
    op.create_index(
        'idx_candidate_home_country',
        'candidate',
        ['tenant_id', 'home_country']
    )
    
    op.create_index(
        'idx_candidate_location',
        'candidate',
        ['tenant_id', 'location']
    )
    
    op.create_index(
        'idx_candidate_current_title',
        'candidate',
        ['tenant_id', 'current_title']
    )
    
    op.create_index(
        'idx_candidate_current_company',
        'candidate',
        ['tenant_id', 'current_company']
    )
    
    op.create_index(
        'idx_candidate_promotability',
        'candidate',
        ['tenant_id', 'promotability_score']
    )
    
    # Index for sorting by updated_at (common in search results)
    op.create_index(
        'idx_candidate_updated_at',
        'candidate',
        ['tenant_id', 'updated_at']
    )
    
    # Index on candidate_assignment for role-based filtering
    op.create_index(
        'idx_candidate_assignment_role',
        'candidate_assignment',
        ['tenant_id', 'role_id', 'status']
    )
    
    op.create_index(
        'idx_candidate_assignment_candidate',
        'candidate_assignment',
        ['tenant_id', 'candidate_id']
    )


def downgrade() -> None:
    """Remove full-text search support."""
    
    # Drop indexes
    op.drop_index('idx_candidate_assignment_candidate', table_name='candidate_assignment')
    op.drop_index('idx_candidate_assignment_role', table_name='candidate_assignment')
    op.drop_index('idx_candidate_updated_at', table_name='candidate')
    op.drop_index('idx_candidate_promotability', table_name='candidate')
    op.drop_index('idx_candidate_current_company', table_name='candidate')
    op.drop_index('idx_candidate_current_title', table_name='candidate')
    op.drop_index('idx_candidate_location', table_name='candidate')
    op.drop_index('idx_candidate_home_country', table_name='candidate')
    op.drop_index('idx_candidate_search_vector', table_name='candidate')
    
    # Drop the tsvector column
    op.execute("ALTER TABLE candidate DROP COLUMN search_vector;")

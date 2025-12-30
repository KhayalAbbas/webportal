"""
Add run-scoped unique constraint to source_documents.

Adds UNIQUE constraint on (tenant_id, company_research_run_id, content_hash)
to enforce that source documents are run-scoped and prevent cross-run contamination.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37bbff09b8b6'
down_revision: Union[str, None] = 'c06d212c49af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - add run-scoped unique constraint."""
    
    # First, clean up any source documents with NULL company_research_run_id
    # These are orphaned records that shouldn't exist per run-scoped design
    op.execute("""
        DELETE FROM source_documents 
        WHERE company_research_run_id IS NULL
    """)
    
    # For now, skip the duplicate handling and just enforce NOT NULL
    # The unique constraint addition will fail if duplicates exist,
    # which is intentional to alert us to the issue
    
    # Make company_research_run_id NOT NULL now that orphaned records are removed
    op.alter_column('source_documents', 'company_research_run_id', nullable=False)
    
    # Try to add unique constraint - this will fail if duplicates exist
    # which is what we want to identify the exact duplicate records
    try:
        op.create_unique_constraint(
            'uq_source_documents_run_scoped',
            'source_documents', 
            ['tenant_id', 'company_research_run_id', 'content_hash']
        )
    except Exception as e:
        # Re-raise with helpful message about duplicates
        raise Exception(f"Cannot create unique constraint due to duplicate data. "
                       f"Run the proof script to identify duplicate source documents first. "
                       f"Original error: {e}")


def downgrade() -> None:
    """Reverse the migration - remove run-scoped unique constraint."""
    
    # Check if constraint exists before trying to drop it
    from sqlalchemy import inspect
    
    bind = op.get_bind()
    inspector = inspect(bind)
    
    constraints = inspector.get_unique_constraints('source_documents')
    constraint_exists = any(c['name'] == 'uq_source_documents_run_scoped' for c in constraints)
    
    if constraint_exists:
        op.drop_constraint('uq_source_documents_run_scoped', 'source_documents', type_='unique')
    
    # Make company_research_run_id nullable again
    op.alter_column('source_documents', 'company_research_run_id', nullable=True)

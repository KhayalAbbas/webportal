"""Add evidence to source document linkage columns.

Adds source_document_id and source_content_hash to company_prospect_evidence
for hardened linkage to source documents. Backfills existing evidence rows
and adds appropriate indexes and constraints.

Revision ID: a0d2d6fa8553
Revises: 37bbff09b8b6
Create Date: 2025-12-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a0d2d6fa8553'
down_revision: Union[str, None] = '37bbff09b8b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - add linkage columns and backfill data."""
    
    # Step 1: Add new columns (nullable initially)
    print("Adding source_document_id and source_content_hash columns...")
    op.add_column('company_prospect_evidence', 
                  sa.Column('source_document_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('company_prospect_evidence',
                  sa.Column('source_content_hash', sa.String(), nullable=True))
    
    # Step 2: Add foreign key constraint to source_documents
    print("Adding foreign key constraint to source_documents...")
    op.create_foreign_key(
        'fk_company_prospect_evidence_source_document_id',
        'company_prospect_evidence',
        'source_documents',
        ['source_document_id'],
        ['id'],
        ondelete='SET NULL'  # Don't cascade delete evidence when source doc is deleted
    )
    
    # Step 3: Backfill existing evidence rows
    print("Backfilling evidence linkage data...")
    op.execute("""
        UPDATE company_prospect_evidence 
        SET 
            source_document_id = sd.id,
            source_content_hash = sd.content_hash
        FROM company_prospects cp, source_documents sd
        WHERE company_prospect_evidence.company_prospect_id = cp.id
        AND sd.tenant_id = cp.tenant_id 
        AND sd.company_research_run_id = cp.company_research_run_id
        AND (
            company_prospect_evidence.source_name LIKE '%' || sd.content_hash || '%'
            OR company_prospect_evidence.source_name = sd.title
        )
        AND company_prospect_evidence.source_document_id IS NULL
    """)
    
    # Step 4: Add indexes for performance
    print("Adding performance indexes...")
    op.create_index('ix_company_prospect_evidence_source_document_id', 
                    'company_prospect_evidence', ['source_document_id'])
    op.create_index('ix_company_prospect_evidence_source_content_hash',
                    'company_prospect_evidence', ['source_content_hash'])
    
    # Step 5: Add uniqueness constraint to prevent duplicate evidence entries
    # Use columns that exist: source_type, source_name (raw_snippet was dropped in 7a65eac76b2b)
    print("Adding uniqueness constraint for evidence deduplication...")
    op.create_unique_constraint(
        'uq_company_prospect_evidence_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'source_type', 'source_name']
    )
    
    print("Migration completed successfully!")


def downgrade() -> None:
    """Reverse the migration - remove columns and constraints."""
    
    # Drop constraints and indexes
    op.drop_constraint('uq_company_prospect_evidence_dedup', 'company_prospect_evidence', type_='unique')
    op.drop_index('ix_company_prospect_evidence_source_content_hash', 'company_prospect_evidence')
    op.drop_index('ix_company_prospect_evidence_source_document_id', 'company_prospect_evidence')
    
    # Drop foreign key
    op.drop_constraint('fk_company_prospect_evidence_source_document_id', 'company_prospect_evidence', type_='foreignkey')
    
    # Drop columns
    op.drop_column('company_prospect_evidence', 'source_content_hash')
    op.drop_column('company_prospect_evidence', 'source_document_id')

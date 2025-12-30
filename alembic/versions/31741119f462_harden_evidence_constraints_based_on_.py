"""Harden evidence constraints based on cardinality analysis

Revision ID: 31741119f462
Revises: 4ab2860cc84b
Create Date: 2025-12-30 23:25:00.000000

This migration hardens constraints based on cardinality analysis:
1. Fixes the overly strict unique constraint for unlinked evidence
2. Adds check constraints for data integrity
3. Adds partial unique constraints for better flexibility
4. Adds foreign key constraint optimization

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31741119f462'
down_revision: Union[str, None] = '4ab2860cc84b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply constraint hardening."""
    
    # Step 1: Drop the overly strict unique constraint that doesn't handle NULLs properly
    op.drop_constraint('uq_company_prospect_evidence_safe_dedup', 'company_prospect_evidence', type_='unique')
    
    # Step 2: Create a partial unique constraint for linked evidence only
    # This prevents duplicate evidence when source_document_id is set
    op.execute("""
        CREATE UNIQUE INDEX uq_company_prospect_evidence_linked_dedup
        ON company_prospect_evidence (tenant_id, company_prospect_id, source_document_id, source_type, source_name)
        WHERE source_document_id IS NOT NULL
    """)
    
    # Step 3: Create a separate partial unique constraint for unlinked evidence
    # This allows multiple unlinked evidence per prospect/type/name but prevents exact URL duplicates
    op.execute("""
        CREATE UNIQUE INDEX uq_company_prospect_evidence_unlinked_dedup
        ON company_prospect_evidence (tenant_id, company_prospect_id, source_type, source_name, source_url)
        WHERE source_document_id IS NULL AND source_url IS NOT NULL
    """)
    
    # Step 4: Add check constraint to ensure linked evidence has proper source data
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_linked_evidence_has_source_data
        CHECK (
            (source_document_id IS NULL) OR 
            (source_document_id IS NOT NULL AND source_content_hash IS NOT NULL AND source_url IS NOT NULL)
        )
    """)
    
    # Step 5: Add check constraint to prevent orphaned hash without document
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_no_orphaned_content_hash
        CHECK (
            (source_content_hash IS NULL) OR 
            (source_content_hash IS NOT NULL AND source_document_id IS NOT NULL)
        )
    """)
    
    # Step 6: Add check constraint for reasonable evidence weight values
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_evidence_weight_range
        CHECK (evidence_weight >= 0.0 AND evidence_weight <= 1.0)
    """)
    
    # Step 7: Optimize foreign key constraint with additional index
    op.create_index(
        'ix_company_prospect_evidence_fk_optimization',
        'company_prospect_evidence',
        ['company_prospect_id', 'tenant_id']
    )


def downgrade() -> None:
    """Reverse constraint hardening."""
    
    # Drop new indexes and constraints
    op.drop_index('ix_company_prospect_evidence_fk_optimization', table_name='company_prospect_evidence')
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_evidence_weight_range")
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_no_orphaned_content_hash")
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_linked_evidence_has_source_data")
    op.execute("DROP INDEX uq_company_prospect_evidence_unlinked_dedup")
    op.execute("DROP INDEX uq_company_prospect_evidence_linked_dedup")
    
    # Restore old unique constraint (but this was problematic)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_safe_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'source_type', 'source_name']
    )

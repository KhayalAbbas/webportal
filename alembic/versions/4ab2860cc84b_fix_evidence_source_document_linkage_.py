"""Fix evidence source document linkage with tenant and run safety

Revision ID: 4ab2860cc84b
Revises: a0d2d6fa8553
Create Date: 2025-12-30 23:15:00.000000

This migration fixes the evidence-to-source document linkage by:
1. Clearing existing incorrect links
2. Re-linking with proper tenant and run constraints
3. Adding a stronger unique constraint for data integrity
4. Adding performance indexes

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ab2860cc84b'
down_revision: Union[str, None] = 'a0d2d6fa8553'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration - fix evidence linkage with safety."""
    
    # Step 1: Clear existing incorrect links to start fresh
    op.execute("""
        UPDATE company_prospect_evidence 
        SET source_document_id = NULL,
            source_content_hash = NULL
        WHERE source_document_id IS NOT NULL
    """)
    
    # Step 2: Drop the existing looser unique constraint
    op.drop_constraint('uq_company_prospect_evidence_dedup', 'company_prospect_evidence', type_='unique')
    
    # Step 3: Re-link evidence to source documents with proper tenant/run constraints
    # This ensures evidence only links to source documents from the same tenant and research run
    op.execute("""
        UPDATE company_prospect_evidence 
        SET source_document_id = sd.id,
            source_content_hash = sd.content_hash
        FROM source_documents sd, company_prospects cp
        WHERE 
            -- Join conditions
            company_prospect_evidence.company_prospect_id = cp.id
            -- Ensure tenant consistency
            AND company_prospect_evidence.tenant_id = cp.tenant_id 
            AND cp.tenant_id = sd.tenant_id
            -- Ensure run consistency
            AND cp.company_research_run_id = sd.company_research_run_id
            -- Match on URL if available
            AND company_prospect_evidence.source_url IS NOT NULL 
            AND sd.url IS NOT NULL
            AND company_prospect_evidence.source_url = sd.url
            -- Only update unlinked records
            AND company_prospect_evidence.source_document_id IS NULL
    """)
    
    # Step 4: Create a stricter unique constraint to prevent future violations
    # This prevents duplicate evidence per (tenant, prospect, source_document, source_type, source_name)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_safe_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'source_type', 'source_name']
    )
    
    # Step 5: Add performance index for tenant-scoped queries
    op.create_index(
        'ix_company_prospect_evidence_tenant_linkage',
        'company_prospect_evidence',
        ['tenant_id', 'source_document_id', 'company_prospect_id']
    )
    
    # Step 6: Add index for evidence fingerprinting (for future deduplication)
    op.create_index(
        'ix_company_prospect_evidence_fingerprint',
        'company_prospect_evidence', 
        ['tenant_id', 'source_type', 'source_name', 'source_content_hash']
    )


def downgrade() -> None:
    """Reverse the migration - restore previous state."""
    
    # Drop new indexes
    op.drop_index('ix_company_prospect_evidence_fingerprint', table_name='company_prospect_evidence')
    op.drop_index('ix_company_prospect_evidence_tenant_linkage', table_name='company_prospect_evidence')
    
    # Drop new unique constraint
    op.drop_constraint('uq_company_prospect_evidence_safe_dedup', 'company_prospect_evidence', type_='unique')
    
    # Restore old unique constraint (looser)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'raw_snippet']
    )

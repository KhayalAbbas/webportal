"""add company research tables

Revision ID: 005_company_research
Revises: d11fc563f724
Create Date: 2025-12-11

This migration adds 4 new tables for the Company Discovery / Agentic Sourcing Engine:
- company_research_run: Discovery exercises for specific mandates
- company_prospect: Potential companies with AI + manual ranking
- company_prospect_evidence: Evidence sources for each prospect
- company_prospect_metric: Numeric metrics with currency conversion

Phase 1: Backend structures only, no external AI orchestration yet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_company_research'
down_revision: Union[str, None] = 'd11fc563f724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create company research tables.
    """
    
    # 1. company_research_run
    op.create_table(
        'company_research_run',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_mandate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['role_mandate_id'], ['role.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_company_research_run_role_mandate_id', 'company_research_run', ['role_mandate_id'])
    op.create_index('ix_company_research_run_status', 'company_research_run', ['status'])
    
    # 2. company_prospect
    op.create_table(
        'company_prospect',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_research_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('name_normalized', sa.String(length=255), nullable=True),
        sa.Column('website', sa.String(length=500), nullable=True),
        sa.Column('linkedin_url', sa.String(length=500), nullable=True),
        sa.Column('headquarters_location', sa.String(length=255), nullable=True),
        sa.Column('country_code', sa.String(length=10), nullable=True),
        sa.Column('industry_sector', sa.String(length=255), nullable=True),
        sa.Column('brief_description', sa.Text(), nullable=True),
        
        # AI-calculated fields
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('evidence_score', sa.Float(), nullable=True),
        
        # Manual override fields
        sa.Column('manual_priority', sa.Integer(), nullable=True),
        sa.Column('manual_notes', sa.Text(), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default='false'),
        
        # Workflow
        sa.Column('status', sa.String(length=50), nullable=False, server_default='new'),
        sa.Column('converted_to_company_id', postgresql.UUID(as_uuid=True), nullable=True),
        
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_research_run_id'], ['company_research_run.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['converted_to_company_id'], ['company.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_company_prospect_company_research_run_id', 'company_prospect', ['company_research_run_id'])
    op.create_index('ix_company_prospect_status', 'company_prospect', ['status'])
    op.create_index('ix_company_prospect_name_normalized', 'company_prospect', ['name_normalized'])
    op.create_index('ix_company_prospect_relevance_score', 'company_prospect', ['relevance_score'])
    op.create_index('ix_company_prospect_manual_priority', 'company_prospect', ['manual_priority'])
    op.create_index('ix_company_prospect_is_pinned', 'company_prospect', ['is_pinned'])
    
    # 3. company_prospect_evidence
    op.create_table(
        'company_prospect_evidence',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_prospect_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=100), nullable=False),
        sa.Column('source_name', sa.String(length=255), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('evidence_snippet', sa.Text(), nullable=True),
        sa.Column('evidence_weight', sa.Float(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_prospect_id'], ['company_prospect.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_company_prospect_evidence_company_prospect_id', 'company_prospect_evidence', ['company_prospect_id'])
    op.create_index('ix_company_prospect_evidence_source_type', 'company_prospect_evidence', ['source_type'])
    
    # 4. company_prospect_metric
    op.create_table(
        'company_prospect_metric',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_prospect_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric_type', sa.String(length=100), nullable=False),
        sa.Column('value_raw', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('value_usd', sa.Float(), nullable=True),
        sa.Column('as_of_year', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=500), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_prospect_id'], ['company_prospect.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_company_prospect_metric_company_prospect_id', 'company_prospect_metric', ['company_prospect_id'])
    op.create_index('ix_company_prospect_metric_metric_type', 'company_prospect_metric', ['metric_type'])
    op.create_index('ix_company_prospect_metric_type_year', 'company_prospect_metric', ['metric_type', 'as_of_year'])


def downgrade() -> None:
    """
    Drop company research tables.
    """
    op.drop_table('company_prospect_metric')
    op.drop_table('company_prospect_evidence')
    op.drop_table('company_prospect')
    op.drop_table('company_research_run')

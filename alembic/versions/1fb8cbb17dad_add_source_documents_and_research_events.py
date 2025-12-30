"""add_source_documents_and_research_events

Revision ID: 1fb8cbb17dad
Revises: 42e42baff25d
Create Date: 2025-12-22

Add SourceDocument and ResearchEvent tables for Phase 2A - source-driven discovery.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fb8cbb17dad'
down_revision: Union[str, None] = '42e42baff25d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create source_documents and research_events tables."""
    
    # 1. source_documents table
    op.create_table(
        'source_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_research_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='new'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_research_run_id'], ['company_research_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes for source_documents
    op.create_index('ix_source_documents_run_id', 'source_documents', ['company_research_run_id'])
    op.create_index('ix_source_documents_status', 'source_documents', ['status'])
    op.create_index('ix_source_documents_hash', 'source_documents', ['content_hash'])
    
    # 2. research_events table
    op.create_table(
        'research_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_research_run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('input_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_research_run_id'], ['company_research_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes for research_events
    op.create_index('ix_research_events_run_id', 'research_events', ['company_research_run_id'])
    op.create_index('ix_research_events_type', 'research_events', ['event_type'])
    op.create_index('ix_research_events_status', 'research_events', ['status'])
    op.create_index('ix_research_events_created', 'research_events', ['created_at'])


def downgrade() -> None:
    """Drop source_documents and research_events tables."""
    op.drop_table('research_events')
    op.drop_table('source_documents')

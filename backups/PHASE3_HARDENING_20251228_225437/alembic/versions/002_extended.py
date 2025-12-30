"""add_extended_fields_and_new_tables

Revision ID: 002_extended
Revises: 001_initial
Create Date: 2024-12-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_extended'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add new fields and tables."""
    
    # Add fields to candidate table
    op.add_column('candidate', sa.Column('mobile_1', sa.String(50), nullable=True))
    op.add_column('candidate', sa.Column('mobile_2', sa.String(50), nullable=True))
    op.add_column('candidate', sa.Column('phone_3', sa.String(50), nullable=True))
    op.add_column('candidate', sa.Column('email_1', sa.String(255), nullable=True))
    op.add_column('candidate', sa.Column('email_2', sa.String(255), nullable=True))
    op.add_column('candidate', sa.Column('email_3', sa.String(255), nullable=True))
    op.add_column('candidate', sa.Column('postal_code', sa.String(20), nullable=True))
    op.add_column('candidate', sa.Column('home_country', sa.String(100), nullable=True))
    op.add_column('candidate', sa.Column('marital_status', sa.String(50), nullable=True))
    op.add_column('candidate', sa.Column('children_count', sa.Integer(), nullable=True))
    op.add_column('candidate', sa.Column('date_of_birth', sa.DateTime(timezone=True), nullable=True))
    op.add_column('candidate', sa.Column('salary_details', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('education_summary', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('certifications', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('qualifications', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('languages', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('religious_holidays', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('social_links', postgresql.JSONB(), nullable=True))
    op.add_column('candidate', sa.Column('bio', sa.Text(), nullable=True))
    op.add_column('candidate', sa.Column('promotability_score', sa.Integer(), nullable=True))
    op.add_column('candidate', sa.Column('gamification_score', sa.Integer(), nullable=True))
    op.add_column('candidate', sa.Column('technical_score', sa.Integer(), nullable=True))
    
    # Add fields to company table
    op.add_column('company', sa.Column('bd_status', sa.String(50), nullable=True))
    op.add_column('company', sa.Column('bd_last_contacted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('company', sa.Column('bd_owner', sa.String(255), nullable=True))
    op.add_column('company', sa.Column('is_prospect', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('company', sa.Column('is_client', sa.Boolean(), nullable=False, server_default='false'))
    
    # Add fields to contact table
    op.add_column('contact', sa.Column('bd_status', sa.String(50), nullable=True))
    op.add_column('contact', sa.Column('bd_owner', sa.String(255), nullable=True))
    op.add_column('contact', sa.Column('date_of_birth', sa.DateTime(timezone=True), nullable=True))
    op.add_column('contact', sa.Column('work_anniversary_date', sa.DateTime(timezone=True), nullable=True))
    
    # Create assessment_result table
    op.create_table(
        'assessment_result',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidate.id'), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('role.id'), nullable=True),
        sa.Column('assessment_type', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(100), nullable=True),
        sa.Column('score_numeric', sa.Integer(), nullable=True),
        sa.Column('score_label', sa.String(100), nullable=True),
        sa.Column('payload', postgresql.JSONB(), nullable=True),
        sa.Column('taken_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Now add FK to candidate for last_psychometric_result_id
    op.add_column('candidate', sa.Column('last_psychometric_result_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assessment_result.id'), nullable=True))
    
    # Create candidate_assignment table
    op.create_table(
        'candidate_assignment',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidate.id'), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('role.id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('is_hot', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('date_entered', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_stage_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pipeline_stage.id'), nullable=True),
        sa.Column('source', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create task table
    op.create_table(
        'task',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('related_entity_type', sa.String(50), nullable=True),
        sa.Column('related_entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assigned_to_user', sa.String(255), nullable=True),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create list table
    op.create_table(
        'list',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create list_item table
    op.create_table(
        'list_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('list_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('list.id'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create bd_opportunity table
    op.create_table(
        'bd_opportunity',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False, index=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('company.id'), nullable=False),
        sa.Column('contact_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contact.id'), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='open'),
        sa.Column('stage', sa.String(50), nullable=True),
        sa.Column('estimated_value', sa.Numeric(15, 2), nullable=True),
        sa.Column('currency', sa.String(10), nullable=True, server_default='USD'),
        sa.Column('probability', sa.Integer(), nullable=True),
        sa.Column('lost_reason', sa.String(100), nullable=True),
        sa.Column('lost_reason_detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    """Remove new fields and tables."""
    op.drop_table('bd_opportunity')
    op.drop_table('list_item')
    op.drop_table('list')
    op.drop_table('task')
    op.drop_table('candidate_assignment')
    
    op.drop_column('candidate', 'last_psychometric_result_id')
    op.drop_table('assessment_result')
    
    op.drop_column('contact', 'work_anniversary_date')
    op.drop_column('contact', 'date_of_birth')
    op.drop_column('contact', 'bd_owner')
    op.drop_column('contact', 'bd_status')
    
    op.drop_column('company', 'is_client')
    op.drop_column('company', 'is_prospect')
    op.drop_column('company', 'bd_owner')
    op.drop_column('company', 'bd_last_contacted_at')
    op.drop_column('company', 'bd_status')
    
    op.drop_column('candidate', 'technical_score')
    op.drop_column('candidate', 'gamification_score')
    op.drop_column('candidate', 'promotability_score')
    op.drop_column('candidate', 'bio')
    op.drop_column('candidate', 'social_links')
    op.drop_column('candidate', 'religious_holidays')
    op.drop_column('candidate', 'languages')
    op.drop_column('candidate', 'qualifications')
    op.drop_column('candidate', 'certifications')
    op.drop_column('candidate', 'education_summary')
    op.drop_column('candidate', 'salary_details')
    op.drop_column('candidate', 'date_of_birth')
    op.drop_column('candidate', 'children_count')
    op.drop_column('candidate', 'marital_status')
    op.drop_column('candidate', 'home_country')
    op.drop_column('candidate', 'postal_code')
    op.drop_column('candidate', 'email_3')
    op.drop_column('candidate', 'email_2')
    op.drop_column('candidate', 'email_1')
    op.drop_column('candidate', 'phone_3')
    op.drop_column('candidate', 'mobile_2')
    op.drop_column('candidate', 'mobile_1')

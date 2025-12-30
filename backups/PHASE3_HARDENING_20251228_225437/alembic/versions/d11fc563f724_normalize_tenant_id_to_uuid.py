"""normalize tenant_id to uuid

Revision ID: d11fc563f724
Revises: 004_candidate_search_fts
Create Date: 2025-12-11

This migration converts all tenant_id columns from VARCHAR to UUID.
All affected tables currently have tenant_id as character varying,
but the models now use UUID type for consistency.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd11fc563f724'
down_revision: Union[str, None] = '004_candidate_search_fts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Convert all tenant_id columns from VARCHAR to UUID.
    
    Tables affected:
    - activity_log
    - ai_enrichment_record
    - assessment_result
    - bd_opportunity
    - candidate
    - candidate_assignment
    - company
    - contact
    - list
    - list_item
    - pipeline_stage
    - research_event
    - role
    - source_document
    - task
    """
    
    # List of all tables that need tenant_id conversion
    tables = [
        'activity_log',
        'ai_enrichment_record',
        'assessment_result',
        'bd_opportunity',
        'candidate',
        'candidate_assignment',
        'company',
        'contact',
        'list',
        'list_item',
        'pipeline_stage',
        'research_event',
        'role',
        'source_document',
        'task',
    ]
    
    for table_name in tables:
        # Drop the index first if it exists
        try:
            op.drop_index(f'ix_{table_name}_tenant_id', table_name=table_name)
        except:
            pass  # Index might not exist
        
        # Alter the column type from VARCHAR to UUID
        # Using USING clause to cast existing values
        op.execute(f"""
            ALTER TABLE {table_name}
            ALTER COLUMN tenant_id TYPE uuid USING tenant_id::uuid;
        """)
        
        # Recreate the index
        op.create_index(f'ix_{table_name}_tenant_id', table_name, ['tenant_id'])


def downgrade() -> None:
    """
    Convert all tenant_id columns back from UUID to VARCHAR.
    
    This is the reverse operation in case we need to rollback.
    """
    
    tables = [
        'activity_log',
        'ai_enrichment_record',
        'assessment_result',
        'bd_opportunity',
        'candidate',
        'candidate_assignment',
        'company',
        'contact',
        'list',
        'list_item',
        'pipeline_stage',
        'research_event',
        'role',
        'source_document',
        'task',
    ]
    
    for table_name in tables:
        # Drop the index first
        try:
            op.drop_index(f'ix_{table_name}_tenant_id', table_name=table_name)
        except:
            pass
        
        # Alter the column type back to VARCHAR
        op.execute(f"""
            ALTER TABLE {table_name}
            ALTER COLUMN tenant_id TYPE character varying(50) USING tenant_id::text;
        """)
        
        # Recreate the index
        op.create_index(f'ix_{table_name}_tenant_id', table_name, ['tenant_id'])

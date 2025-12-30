"""
Add research run ledger tables for Phase 3 and extend source_documents.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3a5e6ddee21"
down_revision: Union[str, None] = "444899a90d5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # research_runs table
    op.create_table(
        "research_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("company_research_run_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rank_spec", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["company_research_run_id"], ["company_research_runs.id"], ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_runs_created", "research_runs", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_research_runs_status", "research_runs", ["tenant_id", "status"], unique=False)
    op.create_index("ix_research_runs_company_run", "research_runs", ["company_research_run_id"], unique=False)
    
    # Add partial unique constraint using raw SQL
    op.execute(
        "CREATE UNIQUE INDEX uq_research_runs_tenant_idempotency "
        "ON research_runs (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

    # research_run_steps table
    op.create_table(
        "research_run_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.String(length=200), nullable=False),
        sa.Column("step_type", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ok"),
        sa.Column("inputs_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("outputs_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("provider_meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "run_id", "step_key", name="uq_research_run_steps_key"),
    )
    op.create_index("ix_research_run_steps_run", "research_run_steps", ["tenant_id", "run_id"], unique=False)

    # Extend source_documents
    op.add_column("source_documents", sa.Column("mime_type", sa.String(length=100), nullable=True))
    op.add_column(
        "source_documents",
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    # Skip unique constraint due to existing duplicates - can be added manually later if needed


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_research_runs_tenant_idempotency")
    
    op.drop_column("source_documents", "meta")
    op.drop_column("source_documents", "mime_type")

    op.drop_index("ix_research_run_steps_run", table_name="research_run_steps")
    op.drop_table("research_run_steps")

    op.drop_index("ix_research_runs_company_run", table_name="research_runs")
    op.drop_index("ix_research_runs_status", table_name="research_runs")
    op.drop_index("ix_research_runs_created", table_name="research_runs")
    op.drop_table("research_runs")

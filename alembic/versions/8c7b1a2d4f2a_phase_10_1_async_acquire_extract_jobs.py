"""Phase 10.1: async acquire+extract job params/progress

Revision ID: 8c7b1a2d4f2a
Revises: 2b04b1c3c0f3
Create Date: 2026-01-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8c7b1a2d4f2a"
down_revision = "2b04b1c3c0f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_research_jobs",
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "company_research_jobs",
        sa.Column("params_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "company_research_jobs",
        sa.Column("progress_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "company_research_jobs",
        sa.Column("error_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "company_research_jobs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "company_research_jobs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_company_research_jobs_params",
        "company_research_jobs",
        ["tenant_id", "run_id", "job_type", "params_hash"],
        unique=True,
        postgresql_where=sa.text("params_hash IS NOT NULL AND job_type = 'acquire_extract_async'"),
    )


def downgrade() -> None:
    op.drop_index("uq_company_research_jobs_params", table_name="company_research_jobs")
    op.drop_column("company_research_jobs", "finished_at")
    op.drop_column("company_research_jobs", "started_at")
    op.drop_column("company_research_jobs", "error_json")
    op.drop_column("company_research_jobs", "progress_json")
    op.drop_column("company_research_jobs", "params_hash")
    op.drop_column("company_research_jobs", "params_json")

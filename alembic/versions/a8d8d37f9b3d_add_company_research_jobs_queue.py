"""Add company research jobs queue and last_error

Revision ID: a8d8d37f9b3d
Revises: 5d4d0e7f2c1f
Create Date: 2025-12-31 16:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a8d8d37f9b3d"
down_revision: Union[str, None] = "5d4d0e7f2c1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("company_research_runs", sa.Column("last_error", sa.Text(), nullable=True))

    op.create_table(
        "company_research_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("company_research_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False, server_default=sa.text("'company_research_run'")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'queued'"), index=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=200), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_index(
        "ix_company_research_jobs_status_next_retry",
        "company_research_jobs",
        ["tenant_id", "status", "next_retry_at"],
    )
    op.create_index(
        "ix_company_research_jobs_tenant_run",
        "company_research_jobs",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "uq_company_research_jobs_active",
        "company_research_jobs",
        ["tenant_id", "run_id", "job_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_company_research_jobs_active", table_name="company_research_jobs")
    op.drop_index("ix_company_research_jobs_tenant_run", table_name="company_research_jobs")
    op.drop_index("ix_company_research_jobs_status_next_retry", table_name="company_research_jobs")
    op.drop_table("company_research_jobs")
    op.drop_column("company_research_runs", "last_error")

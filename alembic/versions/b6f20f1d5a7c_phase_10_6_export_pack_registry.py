"""Phase 10.6: export pack registry

Revision ID: b6f20f1d5a7c
Revises: 8c7b1a2d4f2a
Create Date: 2026-01-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b6f20f1d5a7c"
down_revision = "8c7b1a2d4f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_research_export_packs",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_pointer", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["company_research_runs.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_research_export_packs_tenant_run_created",
        "company_research_export_packs",
        ["tenant_id", "run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_company_research_export_packs_tenant_sha",
        "company_research_export_packs",
        ["tenant_id", "sha256"],
        unique=False,
    )
    op.create_index(
        "ix_company_research_export_packs_pointer",
        "company_research_export_packs",
        ["tenant_id", "storage_pointer"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_company_research_export_packs_pointer", table_name="company_research_export_packs")
    op.drop_index("ix_company_research_export_packs_tenant_sha", table_name="company_research_export_packs")
    op.drop_index("ix_company_research_export_packs_tenant_run_created", table_name="company_research_export_packs")
    op.drop_table("company_research_export_packs")

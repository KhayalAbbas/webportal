"""phase7_10 executive compare + merge decisions

Revision ID: e3b4e2a7c1d0
Revises: 7c9c3e7cf58e
Create Date: 2026-01-06 22:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3b4e2a7c1d0"
down_revision: Union[str, None] = "7c9c3e7cf58e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "executive_merge_decisions",
        sa.Column("company_research_run_id", sa.UUID(), nullable=False),
        sa.Column("company_prospect_id", sa.UUID(), nullable=True),
        sa.Column("canonical_company_id", sa.UUID(), nullable=True),
        sa.Column("left_executive_id", sa.UUID(), nullable=False),
        sa.Column("right_executive_id", sa.UUID(), nullable=False),
        sa.Column("decision_type", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "evidence_source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "evidence_enrichment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_research_run_id"], ["company_research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_prospect_id"], ["company_prospects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["canonical_company_id"], ["canonical_companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["left_executive_id"], ["executive_prospects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["right_executive_id"], ["executive_prospects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "company_research_run_id",
            "left_executive_id",
            "right_executive_id",
            name="uq_executive_merge_decisions_pair",
        ),
    )
    op.create_index(
        op.f("ix_executive_merge_decisions_run"),
        "executive_merge_decisions",
        ["tenant_id", "company_research_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_executive_merge_decisions_run"), table_name="executive_merge_decisions")
    op.drop_table("executive_merge_decisions")

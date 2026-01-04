"""Phase 4.12 executive discovery tables

Revision ID: 0a4d7b8f6bca
Revises: f6a7db6d5c11
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0a4d7b8f6bca"
down_revision: Union[str, None] = "f6a7db6d5c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "executive_prospects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "company_research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_prospect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_prospects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name_raw", sa.String(length=500), nullable=False),
        sa.Column("name_normalized", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'new'")),
        sa.Column("source_label", sa.String(length=100), nullable=True),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_table(
        "executive_prospect_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "executive_prospect_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executive_prospects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_snippet", sa.Text(), nullable=True),
        sa.Column("evidence_weight", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0.5")),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_content_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_executive_prospects_run_id",
        "executive_prospects",
        ["company_research_run_id"],
    )
    op.create_index(
        "ix_executive_prospects_company_id",
        "executive_prospects",
        ["company_prospect_id"],
    )
    op.create_index(
        "ix_executive_prospects_status",
        "executive_prospects",
        ["status"],
    )
    op.create_index(
        "ix_executive_prospects_name_normalized",
        "executive_prospects",
        ["name_normalized"],
    )
    op.create_unique_constraint(
        "uq_executive_per_company",
        "executive_prospects",
        ["tenant_id", "company_research_run_id", "company_prospect_id", "name_normalized"],
    )

    op.create_index(
        "ix_executive_evidence_prospect",
        "executive_prospect_evidence",
        ["executive_prospect_id"],
    )
    op.create_index(
        "ix_executive_evidence_source_type",
        "executive_prospect_evidence",
        ["source_type"],
    )
    op.create_index(
        "ix_executive_evidence_source_document_id",
        "executive_prospect_evidence",
        ["source_document_id"],
    )
    op.create_index(
        "ix_executive_evidence_source_hash",
        "executive_prospect_evidence",
        ["source_content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_executive_evidence_source_hash", table_name="executive_prospect_evidence")
    op.drop_index("ix_executive_evidence_source_document_id", table_name="executive_prospect_evidence")
    op.drop_index("ix_executive_evidence_source_type", table_name="executive_prospect_evidence")
    op.drop_index("ix_executive_evidence_prospect", table_name="executive_prospect_evidence")
    op.drop_table("executive_prospect_evidence")

    op.drop_constraint("uq_executive_per_company", "executive_prospects", type_="unique")
    op.drop_index("ix_executive_prospects_name_normalized", table_name="executive_prospects")
    op.drop_index("ix_executive_prospects_status", table_name="executive_prospects")
    op.drop_index("ix_executive_prospects_company_id", table_name="executive_prospects")
    op.drop_index("ix_executive_prospects_run_id", table_name="executive_prospects")
    op.drop_table("executive_prospects")

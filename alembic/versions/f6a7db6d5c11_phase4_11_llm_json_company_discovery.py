"""Phase 4.11 external llm_json company discovery

Revision ID: f6a7db6d5c11
Revises: e54d1fa8c93a
Create Date: 2026-01-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f6a7db6d5c11"
down_revision: Union[str, Sequence[str], None] = ("e54d1fa8c93a", "7f3e9b5e2d9b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Company prospects: discovery provenance and triage helpers
    op.add_column(
        "company_prospects",
        sa.Column(
            "discovered_by",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'internal'"),
        ),
    )
    op.add_column(
        "company_prospects",
        sa.Column(
            "verification_status",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'unverified'"),
        ),
    )
    op.add_column(
        "company_prospects",
        sa.Column(
            "exec_search_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # AI enrichment record: link to run/source and hashing for idempotency
    op.add_column(
        "ai_enrichment_record",
        sa.Column("company_research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("purpose", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("provider", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("input_scope_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "ai_enrichment_record",
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_foreign_key(
        "fk_ai_enrichment_record_source_document",
        "ai_enrichment_record",
        "source_documents",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_ai_enrichment_record_run_hash",
        "ai_enrichment_record",
        ["tenant_id", "company_research_run_id", "content_hash"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_ai_enrichment_llm_json",
        "ai_enrichment_record",
        ["tenant_id", "company_research_run_id", "purpose", "provider", "content_hash"],
    )

    # Idempotent llm_json sources per run/tenant/content_hash
    op.create_index(
        "uq_source_documents_llm_json_hash",
        "source_documents",
        ["tenant_id", "company_research_run_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("source_type = 'llm_json'"),
    )


def downgrade() -> None:
    op.drop_index("uq_source_documents_llm_json_hash", table_name="source_documents")

    op.drop_constraint("uq_ai_enrichment_llm_json", "ai_enrichment_record", type_="unique")
    op.drop_index("ix_ai_enrichment_record_run_hash", table_name="ai_enrichment_record")
    op.drop_constraint("fk_ai_enrichment_record_source_document", "ai_enrichment_record", type_="foreignkey")
    op.drop_column("ai_enrichment_record", "error_message")
    op.drop_column("ai_enrichment_record", "status")
    op.drop_column("ai_enrichment_record", "source_document_id")
    op.drop_column("ai_enrichment_record", "content_hash")
    op.drop_column("ai_enrichment_record", "input_scope_hash")
    op.drop_column("ai_enrichment_record", "provider")
    op.drop_column("ai_enrichment_record", "purpose")
    op.drop_column("ai_enrichment_record", "company_research_run_id")

    op.drop_column("company_prospects", "exec_search_enabled")
    op.drop_column("company_prospects", "verification_status")
    op.drop_column("company_prospects", "discovered_by")
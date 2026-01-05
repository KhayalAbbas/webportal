"""Stage 6.1 entity resolution tables

Revision ID: d7f9c2c4c1aa
Revises: c59fd2c22b8e
Create Date: 2026-01-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7f9c2c4c1aa"
down_revision: Union[str, None] = "c59fd2c22b8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resolved_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "company_research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_research_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_type", sa.String(length=50), nullable=False, index=True),
        sa.Column("canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("match_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "evidence_source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("resolution_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "company_research_run_id",
            "entity_type",
            "canonical_entity_id",
            name="uq_resolved_entities_canonical",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "company_research_run_id",
            "entity_type",
            "resolution_hash",
            name="uq_resolved_entities_hash",
        ),
    )
    op.create_index(
        "ix_resolved_entities_run_type",
        "resolved_entities",
        ["tenant_id", "company_research_run_id", "entity_type"],
    )

    op.create_table(
        "entity_merge_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "company_research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_research_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_type", sa.String(length=50), nullable=False, index=True),
        sa.Column(
            "resolved_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resolved_entities.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("duplicate_entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("match_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "evidence_source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("resolution_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "company_research_run_id",
            "entity_type",
            "canonical_entity_id",
            "duplicate_entity_id",
            name="uq_entity_merge_links_pair",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "company_research_run_id",
            "entity_type",
            "resolution_hash",
            name="uq_entity_merge_links_hash",
        ),
    )
    op.create_index(
        "ix_entity_merge_links_run_type",
        "entity_merge_links",
        ["tenant_id", "company_research_run_id", "entity_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_merge_links_run_type", table_name="entity_merge_links")
    op.drop_table("entity_merge_links")
    op.drop_index("ix_resolved_entities_run_type", table_name="resolved_entities")
    op.drop_table("resolved_entities")

"""Stage 7.1 enrichment assignments

Revision ID: 8f82c5b65b61
Revises: dacba3347552
Create Date: 2026-01-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8f82c5b65b61"
down_revision: Union[str, None] = "dacba3347552"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enrichment_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("target_entity_type", sa.String(length=30), nullable=False, index=True),
        sa.Column("target_canonical_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("value_json", postgresql.JSONB, nullable=False),
        sa.Column("value_normalized", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("derived_by", sa.String(length=50), nullable=False),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("input_scope_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False, index=True),
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
            "target_entity_type",
            "target_canonical_id",
            "field_key",
            "content_hash",
            "source_document_id",
            name="uq_enrichment_assignment_idempotent",
        ),
    )
    op.create_index(
        "ix_enrichment_assignments_tenant_target",
        "enrichment_assignments",
        ["tenant_id", "target_entity_type", "target_canonical_id"],
    )
    op.create_index(
        "ix_enrichment_assignments_source_doc",
        "enrichment_assignments",
        ["source_document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_enrichment_assignments_source_doc", table_name="enrichment_assignments")
    op.drop_index("ix_enrichment_assignments_tenant_target", table_name="enrichment_assignments")
    op.drop_table("enrichment_assignments")

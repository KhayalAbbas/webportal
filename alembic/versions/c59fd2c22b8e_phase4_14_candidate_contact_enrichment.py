"""Phase 4.14 candidate contact enrichment

Revision ID: c59fd2c22b8e
Revises: 0a4d7b8f6bca
Create Date: 2026-01-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c59fd2c22b8e"
down_revision: Union[str, None] = "0a4d7b8f6bca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_contact_point",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value_raw", sa.String(length=500), nullable=False),
        sa.Column("value_normalized", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_document.id", ondelete="SET NULL"),
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
        sa.UniqueConstraint(
            "tenant_id",
            "candidate_id",
            "kind",
            "value_normalized",
            name="uq_candidate_contact_point_value",
        ),
    )
    op.create_index(
        "ix_candidate_contact_point_candidate",
        "candidate_contact_point",
        ["tenant_id", "candidate_id"],
    )
    op.create_index(
        "ix_candidate_contact_point_normalized",
        "candidate_contact_point",
        ["tenant_id", "value_normalized"],
    )

    op.create_unique_constraint(
        "uq_ai_enrichment_content_hash",
        "ai_enrichment_record",
        ["tenant_id", "purpose", "provider", "content_hash", "target_id", "target_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_ai_enrichment_content_hash", "ai_enrichment_record", type_="unique")
    op.drop_index("ix_candidate_contact_point_normalized", table_name="candidate_contact_point")
    op.drop_index("ix_candidate_contact_point_candidate", table_name="candidate_contact_point")
    op.drop_table("candidate_contact_point")

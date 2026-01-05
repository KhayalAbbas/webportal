"""Stage 6.2 canonical people tables

Revision ID: e88e3b16e9f4
Revises: d7f9c2c4c1aa
Create Date: 2026-01-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e88e3b16e9f4"
down_revision: Union[str, None] = "d7f9c2c4c1aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("canonical_full_name", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.Text(), nullable=True),
        sa.Column("primary_linkedin_url", sa.Text(), nullable=True),
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
        "ix_canonical_people_tenant",
        "canonical_people",
        ["tenant_id"],
    )

    op.create_table(
        "canonical_person_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "canonical_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("canonical_people.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email_normalized", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "email_normalized", name="uq_canonical_person_emails_unique_email"),
    )
    op.create_index(
        "ix_canonical_person_emails_tenant_email",
        "canonical_person_emails",
        ["tenant_id", "email_normalized"],
    )

    op.create_table(
        "canonical_person_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "canonical_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("canonical_people.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "person_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executive_prospects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("match_rule", sa.Text(), nullable=False),
        sa.Column(
            "evidence_source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "evidence_company_research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_research_runs.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "person_entity_id", name="uq_canonical_person_links_person"),
    )
    op.create_index(
        "ix_canonical_person_links_tenant_person",
        "canonical_person_links",
        ["tenant_id", "canonical_person_id"],
    )
    op.create_index(
        "ix_canonical_person_links_tenant_run",
        "canonical_person_links",
        ["tenant_id", "evidence_company_research_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_person_links_tenant_run", table_name="canonical_person_links")
    op.drop_index("ix_canonical_person_links_tenant_person", table_name="canonical_person_links")
    op.drop_table("canonical_person_links")

    op.drop_index("ix_canonical_person_emails_tenant_email", table_name="canonical_person_emails")
    op.drop_table("canonical_person_emails")

    op.drop_index("ix_canonical_people_tenant", table_name="canonical_people")
    op.drop_table("canonical_people")

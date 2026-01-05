"""Stage 6.3 canonical companies tables

Revision ID: dacba3347552
Revises: e88e3b16e9f4
Create Date: 2026-01-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "dacba3347552"
down_revision: Union[str, None] = "e88e3b16e9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        sa.Column("primary_domain", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_canonical_companies_tenant", "canonical_companies", ["tenant_id"])

    op.create_table(
        "canonical_company_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "canonical_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("canonical_companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("domain_normalized", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "domain_normalized", name="uq_canonical_company_domains_domain"),
    )
    op.create_index(
        "ix_canonical_company_domains_tenant_domain",
        "canonical_company_domains",
        ["tenant_id", "domain_normalized"],
    )

    op.create_table(
        "canonical_company_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "canonical_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("canonical_companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "company_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_prospects.id", ondelete="CASCADE"),
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
        sa.UniqueConstraint("tenant_id", "company_entity_id", name="uq_canonical_company_links_entity"),
    )
    op.create_index(
        "ix_canonical_company_links_tenant_company",
        "canonical_company_links",
        ["tenant_id", "canonical_company_id"],
    )
    op.create_index(
        "ix_canonical_company_links_tenant_run",
        "canonical_company_links",
        ["tenant_id", "evidence_company_research_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_company_links_tenant_run", table_name="canonical_company_links")
    op.drop_index("ix_canonical_company_links_tenant_company", table_name="canonical_company_links")
    op.drop_table("canonical_company_links")

    op.drop_index("ix_canonical_company_domains_tenant_domain", table_name="canonical_company_domains")
    op.drop_table("canonical_company_domains")

    op.drop_index("ix_canonical_companies_tenant", table_name="canonical_companies")
    op.drop_table("canonical_companies")

"""stage7_5 review status on prospects

Revision ID: 1a2b3c4d5e6f
Revises: 8f82c5b65b61
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1a2b3c4d5e6f"
down_revision = "8f82c5b65b61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_prospects",
        sa.Column(
            "review_status",
            sa.String(length=50),
            nullable=False,
            server_default="new",
        ),
    )
    op.create_index(
        "ix_company_prospects_review_status",
        "company_prospects",
        ["tenant_id", "company_research_run_id", "review_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_prospects_review_status",
        table_name="company_prospects",
    )
    op.drop_column("company_prospects", "review_status")

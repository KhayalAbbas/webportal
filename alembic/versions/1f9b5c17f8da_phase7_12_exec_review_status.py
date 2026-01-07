"""phase7_12 executive review status

Revision ID: 1f9b5c17f8da
Revises: e3b4e2a7c1d0
Create Date: 2026-01-07
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1f9b5c17f8da"
down_revision = "e3b4e2a7c1d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executive_prospects",
        sa.Column(
            "review_status",
            sa.String(length=50),
            nullable=False,
            server_default="new",
        ),
    )
    op.create_index(
        "ix_executive_prospects_review_status",
        "executive_prospects",
        ["tenant_id", "company_research_run_id", "review_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_executive_prospects_review_status",
        table_name="executive_prospects",
    )
    op.drop_column("executive_prospects", "review_status")

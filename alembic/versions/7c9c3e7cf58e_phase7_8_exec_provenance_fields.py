"""phase7_8 exec provenance fields

Revision ID: 7c9c3e7cf58e
Revises: 1a2b3c4d5e6f
Create Date: 2026-01-06 19:20:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7c9c3e7cf58e"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executive_prospects") as batch:
        batch.add_column(
            sa.Column(
                "discovered_by",
                sa.String(length=50),
                nullable=False,
                server_default="internal",
            )
        )
        batch.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=50),
                nullable=False,
                server_default="unverified",
            )
        )

    # Ensure existing rows have defaults applied
    op.execute(
        "UPDATE executive_prospects "
        "SET discovered_by = COALESCE(discovered_by, 'internal'), "
        "verification_status = COALESCE(verification_status, 'unverified')"
    )

    with op.batch_alter_table("executive_prospects") as batch:
        batch.alter_column("discovered_by", server_default=None)
        batch.alter_column("verification_status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("executive_prospects") as batch:
        batch.drop_column("verification_status")
        batch.drop_column("discovered_by")

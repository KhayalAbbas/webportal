"""Phase 8.2: add executive->ATS linkage columns"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2b04b1c3c0f3"
down_revision = "1f9b5c17f8da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executive_prospects",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "executive_prospects",
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "executive_prospects",
        sa.Column("candidate_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_executive_prospects_candidate",
        "executive_prospects",
        "candidate",
        ["candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_executive_prospects_contact",
        "executive_prospects",
        "contact",
        ["contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_executive_prospects_assignment",
        "executive_prospects",
        "candidate_assignment",
        ["candidate_assignment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_executive_prospects_assignment", "executive_prospects", type_="foreignkey")
    op.drop_constraint("fk_executive_prospects_contact", "executive_prospects", type_="foreignkey")
    op.drop_constraint("fk_executive_prospects_candidate", "executive_prospects", type_="foreignkey")
    op.drop_column("executive_prospects", "candidate_assignment_id")
    op.drop_column("executive_prospects", "contact_id")
    op.drop_column("executive_prospects", "candidate_id")

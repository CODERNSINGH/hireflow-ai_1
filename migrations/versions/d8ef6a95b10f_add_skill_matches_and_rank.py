"""add skill_matches and rank columns to applications

Revision ID: d8ef6a95b10f
Revises: c7df5d84a09e
Create Date: 2026-07-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8ef6a95b10f"
down_revision: Union[str, None] = "c7df5d84a09e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add skill_matches and rank columns to applications table."""
    op.add_column(
        "applications",
        sa.Column("skill_matches", sa.String(), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("rank", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Remove skill_matches and rank columns from applications table."""
    op.drop_column("applications", "rank")
    op.drop_column("applications", "skill_matches")

"""add cycle_start_date column to applications

Revision ID: 1a2b3c4d5e6f
Revises: d8ef6a95b10f
Create Date: 2026-07-27 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "d8ef6a95b10f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cycle_start_date column to applications table."""
    op.add_column(
        "applications",
        sa.Column("cycle_start_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Remove cycle_start_date column from applications table."""
    op.drop_column("applications", "cycle_start_date")

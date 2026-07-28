"""add resume_version column to applications

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-28 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7g"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add resume_version column to applications table."""
    op.add_column(
        "applications",
        sa.Column("resume_version", sa.Integer(), nullable=True, server_default="1"),
    )


def downgrade() -> None:
    """Remove resume_version column from applications table."""
    op.drop_column("applications", "resume_version")

"""Add remaining tables

Revision ID: 5f3efb65cd1d
Revises: c7df5d84a09e
Create Date: 2026-07-11 12:32:22.278444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f3efb65cd1d'
down_revision: Union[str, Sequence[str], None] = 'c7df5d84a09e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

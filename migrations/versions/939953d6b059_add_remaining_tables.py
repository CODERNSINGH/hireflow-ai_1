"""Add remaining tables

Revision ID: 939953d6b059
Revises: 5f3efb65cd1d
Create Date: 2026-07-11 12:33:20.693443

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '939953d6b059'
down_revision: Union[str, Sequence[str], None] = '5f3efb65cd1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""rename user active to status

Revision ID: b7e1c4a92d10
Revises: 0798a3fc5f63
Create Date: 2026-10-06 16:02:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b7e1c4a92d10"
down_revision: Union[str, Sequence[str], None] = "0798a3fc5f63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "active", new_column_name="status")


def downgrade() -> None:
    op.alter_column("users", "status", new_column_name="active")

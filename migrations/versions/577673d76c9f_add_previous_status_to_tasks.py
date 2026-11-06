"""add previous status to tasks

Revision ID: 577673d76c9f
Revises: 6093189fb044
Create Date: 2026-11-06 13:13:03.744114

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '577673d76c9f'
down_revision: Union[str, None] = '6093189fb044'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("previous_status", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "previous_status")

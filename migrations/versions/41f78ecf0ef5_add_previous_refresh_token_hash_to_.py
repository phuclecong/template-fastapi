"""add previous refresh token hash to sessions

Revision ID: 41f78ecf0ef5
Revises: 63f949b1c6ab
Create Date: 2026-11-06 12:25:11.075143

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41f78ecf0ef5'
down_revision: Union[str, None] = '63f949b1c6ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "previous_refresh_token_hash")

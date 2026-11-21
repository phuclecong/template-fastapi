"""add roles and user role identity; convert task due dates to instants

Revision ID: 8d6f4c2a1b90
Revises: 577673d76c9f
Create Date: 2026-11-21 10:00:00.000000

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d6f4c2a1b90'
down_revision: Union[str, None] = '577673d76c9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in step with app.core.seed.SYSTEM_ROLE_TIMESTAMP / SYSTEM_ROLE_SEEDS.
SYSTEM_ROLE_TIMESTAMP = datetime(2024, 1, 1, tzinfo=UTC)
SYSTEM_ROLE_SEEDS = (
    {
        "id": "rol_admin",
        "title": "Administrator",
        "description": "Full access to workspace administration.",
        "status": "active",
    },
    {
        "id": "rol_member",
        "title": "Member",
        "description": "Standard workspace member.",
        "status": "active",
    },
)


def _sqlite_tasks_for_copy(due_date_type: sa.types.TypeEngine) -> sa.Table:
    """Reflect ``tasks`` and declare ``due_date`` with ``due_date_type``.

    Alembic's SQLite batch copy decides whether to emit ``CAST`` from the reflected
    old column type, so overriding it here keeps the normalized values intact.
    """
    table = sa.Table("tasks", sa.MetaData(), autoload_with=op.get_bind())
    table.c.due_date.type = due_date_type
    return table


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive title uniqueness (SQLite and PostgreSQL both support
    # expression indexes on lower(title)).
    op.create_index(
        "ix_roles_title_lower",
        "roles",
        [sa.text("lower(title)")],
        unique=True,
    )

    roles_table = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.String),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        roles_table,
        [
            {
                **seed,
                "created_at": SYSTEM_ROLE_TIMESTAMP,
                "updated_at": SYSTEM_ROLE_TIMESTAMP,
            }
            for seed in SYSTEM_ROLE_SEEDS
        ],
    )

    # Add the Role identity, backfill from the legacy string, then drop it.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role_id", sa.String(length=40), nullable=True))
        batch.create_foreign_key(
            "fk_users_role_id_roles",
            "roles",
            ["role_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        sa.text(
            "UPDATE users SET role_id = CASE "
            "WHEN role = 'admin' THEN 'rol_admin' "
            "ELSE 'rol_member' END"
        )
    )

    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "role_id",
            existing_type=sa.String(length=40),
            nullable=False,
        )
        batch.drop_column("role")
    op.create_index("ix_users_role_id", "users", ["role_id"], unique=False)

    # Calendar-date Due dates become timezone-aware instants at UTC midnight.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE tasks SET due_date = due_date || ' 00:00:00' "
                "WHERE due_date IS NOT NULL"
            )
        )
        with op.batch_alter_table(
            "tasks", copy_from=_sqlite_tasks_for_copy(sa.DateTime(timezone=True))
        ) as batch:
            # ``copy_from`` makes Alembic treat the old column as DateTime, so it
            # skips its batch CAST. ``CAST('2026-03-04 00:00:00' AS DATETIME)`` has
            # NUMERIC affinity and would silently truncate the value to ``2026``.
            batch.alter_column(
                "due_date",
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(timezone=True),
                existing_nullable=True,
            )
    else:
        op.execute(
            sa.text(
                "ALTER TABLE tasks ALTER COLUMN due_date "
                "TYPE TIMESTAMP WITH TIME ZONE "
                "USING due_date::timestamp AT TIME ZONE 'UTC'"
            )
        )


def downgrade() -> None:
    """Best-effort reversal: restore users.role and calendar-date Due dates."""
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE tasks SET due_date = substr(due_date, 1, 10) "
                "WHERE due_date IS NOT NULL"
            )
        )
        with op.batch_alter_table(
            "tasks", copy_from=_sqlite_tasks_for_copy(sa.Date())
        ) as batch:
            # See the upgrade note: matching affinities avoid a lossy CAST.
            batch.alter_column(
                "due_date",
                existing_type=sa.Date(),
                type_=sa.Date(),
                existing_nullable=True,
            )
    else:
        op.execute(
            sa.text(
                "ALTER TABLE tasks ALTER COLUMN due_date TYPE DATE "
                "USING (due_date AT TIME ZONE 'UTC')::date"
            )
        )

    op.drop_index("ix_users_role_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(length=16), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET role = CASE "
            "WHEN role_id = 'rol_admin' THEN 'admin' "
            "ELSE 'member' END"
        )
    )
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(length=16),
            nullable=False,
        )
        batch.drop_constraint("fk_users_role_id_roles", type_="foreignkey")
        batch.drop_column("role_id")

    op.drop_index("ix_roles_title_lower", table_name="roles")
    op.drop_table("roles")

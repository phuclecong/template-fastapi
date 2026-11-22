"""Verify Alembic migrations run against SQLite and preserve legacy data."""

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.time import ensure_utc

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "577673d76c9f"


def _config(db_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


def test_alembic_upgrade_runs_against_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    config = _config(db_path)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
    finally:
        engine.dispose()

    assert "alembic_version" in tables


def _seed_legacy_rows(db_path: Path) -> None:
    """Insert the pre-Role rows the migration must backfill."""
    engine = create_engine(f"sqlite:///{db_path}")
    users = [
        {
            "id": "user-admin",
            "name": "Admin",
            "email": "admin@example.com",
            "hashed_password": "hash",
            "role": "admin",
        },
        {
            "id": "user-member",
            "name": "Member",
            "email": "member@example.com",
            "hashed_password": "hash",
            "role": "member",
        },
        {
            "id": "user-unknown",
            "name": "Unknown",
            "email": "unknown@example.com",
            "hashed_password": "hash",
            "role": "superadmin",
        },
    ]
    tasks = [
        {
            "id": "task-dated",
            "title": "Dated",
            "description": None,
            "status": "todo",
            "priority": None,
            "assignee_id": "user-admin",
            "due_date": "2026-03-04",
        },
        {
            "id": "task-undated",
            "title": "Undated",
            "description": None,
            "status": "todo",
            "priority": None,
            "assignee_id": None,
            "due_date": None,
        },
    ]
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, name, email, hashed_password, role, created_at) "
                    "VALUES (:id, :name, :email, :hashed_password, :role, :created_at)"
                ),
                [{**user, "created_at": "2026-01-01 00:00:00.000000"} for user in users],
            )
            connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id, title, description, status, priority, assignee_id, due_date, "
                    "created_at, updated_at) "
                    "VALUES (:id, :title, :description, :status, :priority, :assignee_id, "
                    ":due_date, :created_at, :updated_at)"
                ),
                [
                    {
                        **task,
                        "created_at": "2026-01-01 00:00:00.000000",
                        "updated_at": "2026-01-01 00:00:00.000000",
                    }
                    for task in tasks
                ],
            )
    finally:
        engine.dispose()


def test_migration_backfills_roles_and_converts_due_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    config = _config(db_path)

    command.upgrade(config, PREVIOUS_HEAD)
    _seed_legacy_rows(db_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            role_rows = connection.execute(
                text("SELECT id, title, status FROM roles ORDER BY id")
            ).all()
            user_rows = connection.execute(text("SELECT id, role_id FROM users ORDER BY id")).all()

            tasks = sa.Table("tasks", sa.MetaData(), autoload_with=connection)
            task_rows = connection.execute(
                sa.select(tasks.c.id, tasks.c.due_date).order_by(tasks.c.id)
            ).all()
            due_date_type = tasks.c.due_date.type
    finally:
        engine.dispose()

    # The Role table exists with exactly the two seeded System Roles.
    assert [tuple(row) for row in role_rows] == [
        ("rol_admin", "Administrator", "active"),
        ("rol_member", "Member", "active"),
    ]

    # role_id is backfilled: admin -> rol_admin, member -> rol_member, anything else
    # -> rol_member. The legacy string column is gone.
    assert "role" not in user_columns
    assert {row[0]: row[1] for row in user_rows} == {
        "user-admin": "rol_admin",
        "user-member": "rol_member",
        "user-unknown": "rol_member",
    }

    # Due dates are instants now; legacy date-only values become UTC midnight.
    assert isinstance(due_date_type, sa.DateTime)
    due_dates = {row[0]: row[1] for row in task_rows}
    assert due_dates["task-dated"] is not None
    assert ensure_utc(due_dates["task-dated"]) == datetime(2026, 3, 4, tzinfo=UTC)
    assert due_dates["task-undated"] is None


def test_migration_upgrades_and_downgrades_on_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "roundtrip.db"
    config = _config(db_path)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            role_id_type = next(
                column["type"]
                for column in inspector.get_columns("roles")
                if column["name"] == "id"
            )
            user_role_id_type = next(
                column["type"]
                for column in inspector.get_columns("users")
                if column["name"] == "role_id"
            )
    finally:
        engine.dispose()

    # ``rol_`` + UUID is 40 chars; both the Role id and its foreign key must fit.
    assert isinstance(role_id_type, sa.String)
    assert role_id_type.length == 40
    assert isinstance(user_role_id_type, sa.String)
    assert user_role_id_type.length == 40

    command.downgrade(config, PREVIOUS_HEAD)

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            user_columns = {column["name"] for column in inspector.get_columns("users")}
    finally:
        engine.dispose()

    assert "roles" not in tables
    assert "role_id" not in user_columns
    assert "role" in user_columns

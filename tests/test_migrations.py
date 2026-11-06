"""Verify Alembic migration scaffolding runs against SQLite."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_runs_against_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", async_url)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
    finally:
        engine.dispose()

    assert "alembic_version" in tables

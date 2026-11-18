"""Apply Alembic migrations programmatically (used at startup and in tests)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # '%' must be escaped for ConfigParser interpolation
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(_config(database_url), "head")


def downgrade_to(database_url: str, revision: str) -> None:
    command.downgrade(_config(database_url), revision)

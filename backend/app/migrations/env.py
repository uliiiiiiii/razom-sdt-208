"""Alembic environment. Migrations are hand-written SQL (no autogenerate)."""
import os

from alembic import context
from sqlalchemy import create_engine

url = context.config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()

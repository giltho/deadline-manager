"""Alembic environment for deadline-manager.

Uses a synchronous SQLite connection (required by Alembic's standard runner)
against the same database path that db.py uses.  The RAILWAY_VOLUME_MOUNT_PATH
env-var is honoured so the correct file is migrated on Railway.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import metadata so Alembic can inspect current schema
from sqlmodel import SQLModel

import models  # noqa: F401 — registers all table metadata

# ── Alembic Config object ─────────────────────────────────────────────────────

config = context.config

# Wire up the DB URL the same way db.py does
_db_dir = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ".")
_DATABASE_URL = f"sqlite:///{_db_dir}/deadlines.db"  # sync driver for Alembic
config.set_main_option("sqlalchemy.url", _DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


# ── Migration helpers ─────────────────────────────────────────────────────────


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live DB connection."""
    context.configure(
        url=_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE emulation
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

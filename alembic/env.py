from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from aval.infrastructure.sqlite.models import metadata


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    """Migrate the database the application actually opens.

    `alembic.ini` names a path, and the application reads `AVAL_DATABASE_PATH`. When
    those disagreed, `alembic upgrade head` migrated a file nothing ever opened — and
    nobody noticed, because the composition root calls `metadata.create_all` and builds
    the schema underneath. That hides drift exactly where it costs the most: a migration
    that alters or backfills a table would run against an empty stand-in while the live
    database silently kept the old shape.
    """
    configured = os.environ.get("AVAL_DATABASE_PATH", "").strip()
    if not configured or configured.lower() == ":memory:":
        return config.get_main_option("sqlalchemy.url")
    path = Path(configured)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path.as_posix()}"


config.set_main_option("sqlalchemy.url", _database_url())

target_metadata = metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

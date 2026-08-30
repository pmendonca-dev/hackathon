"""The two ways this database comes into existence must describe the same database.

There are two, and both are legitimate. A deployment runs `alembic upgrade head`, which
is what the demo runbook does. A process starting up runs `metadata.create_all()` in the
composition root, which is what keeps an in-memory instance and every test fast.

Nothing forced them to agree. A migration that forgot a column, or a column added to
`models.py` without a migration, would leave the demo and a deployment running different
schemas — and the failure would surface as a confusing runtime error on whichever path
the team was not using that day, long after the change that caused it.

This is the cheap guard: build the schema both ways and compare. It is deliberately not
a replacement for the migrations, and it does not force startup through Alembic — a
migration on every boot would slow every test in the suite to buy a property that one
comparison already buys once.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from aval.infrastructure.sqlite.models import metadata

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Alembic's own bookkeeping table. It exists only on the migrated database by
# construction, and its absence from the metadata is correct rather than a drift.
ALEMBIC_BOOKKEEPING = {"alembic_version"}


def _schema_of(engine) -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table not in ALEMBIC_BOOKKEEPING
    }


def _migrated_schema(tmp_path: Path) -> dict[str, set[str]]:
    database = tmp_path / "migrated.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    return _schema_of(create_engine(f"sqlite+pysqlite:///{database.as_posix()}"))


def _declared_schema(tmp_path: Path) -> dict[str, set[str]]:
    database = tmp_path / "declared.db"
    engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    metadata.create_all(engine)
    return _schema_of(engine)


def test_migrations_and_models_declare_the_same_tables(tmp_path: Path) -> None:
    migrated = _migrated_schema(tmp_path)
    declared = _declared_schema(tmp_path)

    missing_from_migrations = sorted(set(declared) - set(migrated))
    missing_from_models = sorted(set(migrated) - set(declared))

    assert not missing_from_migrations, (
        "models.py declares tables no migration creates, so a deployment would start "
        f"without them: {missing_from_migrations}"
    )
    assert not missing_from_models, (
        "migrations create tables models.py does not declare, so an in-memory instance "
        f"would start without them: {missing_from_models}"
    )


def test_migrations_and_models_declare_the_same_columns(tmp_path: Path) -> None:
    migrated = _migrated_schema(tmp_path)
    declared = _declared_schema(tmp_path)

    drift = {
        table: {
            "only in models.py": sorted(declared[table] - migrated[table]),
            "only in migrations": sorted(migrated[table] - declared[table]),
        }
        for table in sorted(set(migrated) & set(declared))
        if declared[table] != migrated[table]
    }

    assert not drift, f"the two schema sources disagree: {drift}"

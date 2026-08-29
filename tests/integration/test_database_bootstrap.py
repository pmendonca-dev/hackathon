from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select

from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import CORE_TABLE_NAMES, agent_profiles, metadata
from aval.infrastructure.sqlite.seed import seed_demo_data
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


def test_database_engine_enables_wal_and_foreign_keys(tmp_path):
    database_path = tmp_path / "aval.db"

    engine = create_sqlite_engine(database_path)

    with engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1


def test_write_transaction_uses_begin_immediate(tmp_path):
    engine = create_sqlite_engine(tmp_path / "aval.db")
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    result = run_in_write_transaction(
        engine,
        lambda connection: connection.exec_driver_sql("SELECT 42").scalar_one(),
    )

    assert result == 42
    assert "BEGIN IMMEDIATE" in statements


def test_initial_schema_contains_all_authorization_core_tables():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())
    assert set(CORE_TABLE_NAMES) <= table_names

    reservation_constraints = inspect(engine).get_check_constraints("reservations")
    assert any("PENDING" in constraint["sqltext"] for constraint in reservation_constraints)


def test_alembic_upgrade_creates_the_initial_schema(tmp_path):
    project_root = __file__.replace("\\", "/").split("/tests/")[0]
    config = Config(f"{project_root}/alembic.ini")
    database_path = tmp_path / "migrated.db"
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert set(CORE_TABLE_NAMES) <= set(inspector.get_table_names())
    mandate_columns = {column["name"] for column in inspector.get_columns("mandates")}
    assert {"allowed_categories", "ceiling_minor_units"} <= mandate_columns


def test_seed_is_deterministic_and_idempotent(tmp_path):
    engine = create_sqlite_engine(tmp_path / "seed.db")
    metadata.create_all(engine)

    seed_demo_data(engine)
    seed_demo_data(engine)

    with engine.connect() as connection:
        profiles = connection.execute(select(agent_profiles)).mappings().all()

    assert profiles == [
        {
            "id": "agent_demo",
            "profile_url": "https://agent.aval.local/.well-known/ucp",
            "profile_json": '{"keys":[],"name":"AVAL Demo Agent"}',
            "trusted": 1,
        }
    ]

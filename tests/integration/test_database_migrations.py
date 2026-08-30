from __future__ import annotations

import os
import subprocess
import sys
from alembic import command
from alembic.config import Config
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text

from aval.application.authorization_core import AuthorizationCore
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository
from aval.infrastructure.sqlite.models import idempotency_records


LEGACY_SCHEMA_HEAD = "0012_merge_watches_and_browser_sessions"
LEGACY_SCHEMA_REPAIR = "0013_repair_legacy_mandate_frequency"
#: Where `upgrade head` lands today. Kept apart from the repair revision on purpose:
#: these assertions are about reaching the end of the graph, and the repair stopped
#: being the end of it when the creation-proof branch was merged back in.
CURRENT_HEAD = "0015_merge_creation_proof_and_legacy_repair"


def _project_root() -> Path:
    return Path(__file__).parents[2]


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(_project_root() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    return config


def _head_stamped_legacy_database(tmp_path: Path) -> tuple[Path, Config]:
    """Build only a disposable database whose schema missed the historic column."""
    database_path = tmp_path / "head-stamped-legacy.sqlite3"
    config = _alembic_config(database_path)
    command.upgrade(config, LEGACY_SCHEMA_HEAD)
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO mandates ("
            "id, principal_id, principal_display_name, allowed_merchant_ids, allowed_categories, "
            "status, currency, scale, limit_minor_units, ceiling_minor_units, max_uses, "
            "usage_window_seconds, instrument_token, instrument_label, expires_at, policy_version, "
            "revocation_epoch, revocation_metadata"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "mandate_legacy",
                "holder_legacy",
                "Legacy holder",
                '["merchant_demo"]',
                '["travel"]',
                "ACTIVE",
                "USD",
                2,
                50_000,
                None,
                None,
                None,
                None,
                None,
                "2030-01-01T00:00:00+00:00",
                1,
                0,
                '{"revocation_id":"revocation_legacy","epoch":0}',
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO revocation_authorities ("
            "id, mandate_id, role, kid, public_jwk, allowed_scope"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                "authority_legacy",
                "mandate_legacy",
                "holder",
                "holder-legacy-k1",
                "{}",
                '["mandate"]',
            ),
        )
        connection.exec_driver_sql("ALTER TABLE mandates DROP COLUMN max_uses")
    engine.dispose()
    return database_path, config


def _mandate_columns(database_path: Path) -> set[str]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        return {column["name"] for column in inspect(engine).get_columns("mandates")}
    finally:
        engine.dispose()


def _alembic_version(database_path: Path) -> str:
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_upgrade_repairs_max_uses_for_a_head_stamped_legacy_mandate(tmp_path):
    """Deleting the repair migration would leave a database marked at head unusable."""
    database_path, config = _head_stamped_legacy_database(tmp_path)

    command.upgrade(config, "head")

    assert "max_uses" in _mandate_columns(database_path)
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            # A legacy row carried no frequency rule; None is the domain's only valid backfill.
            assert connection.execute(
                text("SELECT max_uses FROM mandates WHERE id = 'mandate_legacy'")
            ).scalar_one() is None
            repaired = SqliteMandateRepository(connection).get("mandate_legacy")
            assert repaired is not None
            assert repaired.usage_limit is None
    finally:
        engine.dispose()
    assert _alembic_version(database_path) == CURRENT_HEAD


def test_repaired_legacy_database_starts_fastapi_from_the_configured_path(tmp_path):
    """The ASGI composition root must boot from the repaired copy without a reset."""
    database_path, config = _head_stamped_legacy_database(tmp_path)
    command.upgrade(config, "head")
    environment = os.environ.copy() | {"AVAL_DATABASE_PATH": str(database_path)}

    completed = subprocess.run(
        [sys.executable, "-c", "from aval.main import create_app; create_app()"],
        capture_output=True,
        check=False,
        cwd=_project_root(),
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_repair_downgrade_keeps_the_compatibility_column_for_the_demo(tmp_path):
    """A downgrade must not recreate the head-marked legacy defect or lose mandate facts."""
    database_path, config = _head_stamped_legacy_database(tmp_path)
    command.upgrade(config, "head")

    command.downgrade(config, LEGACY_SCHEMA_HEAD)

    assert "max_uses" in _mandate_columns(database_path)
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT max_uses FROM mandates WHERE id = 'mandate_legacy'")
            ).scalar_one() is None
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert _alembic_version(database_path) == CURRENT_HEAD


def test_clean_database_reaches_the_legacy_schema_repair_head(tmp_path):
    """Fresh installs must still traverse the repair migration after the historical graph."""
    database_path = tmp_path / "clean.sqlite3"

    command.upgrade(_alembic_config(database_path), "head")

    assert "max_uses" in _mandate_columns(database_path)
    assert _alembic_version(database_path) == CURRENT_HEAD


def test_upgrade_from_initial_revision_adds_persisted_authorization_hardening(tmp_path):
    """A database stamped at 0001 must gain later persistence guarantees."""
    database_path = tmp_path / "aval-0001.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE mandates ("
            "id VARCHAR PRIMARY KEY, principal_id VARCHAR NOT NULL, status VARCHAR NOT NULL, "
            "currency VARCHAR(3) NOT NULL, scale INTEGER NOT NULL, limit_minor_units INTEGER NOT NULL, "
            "expires_at DATETIME NOT NULL, policy_version INTEGER NOT NULL, revocation_epoch INTEGER NOT NULL, "
            "revocation_metadata TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE reservations ("
            "id VARCHAR PRIMARY KEY, mandate_id VARCHAR NOT NULL, checkout_intent_id VARCHAR NOT NULL, "
            "amount_minor_units INTEGER NOT NULL, status VARCHAR NOT NULL, transaction_hash VARCHAR)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE idempotency_records ("
            "id VARCHAR PRIMARY KEY, scope VARCHAR NOT NULL, idempotency_key VARCHAR NOT NULL, "
            "request_hash VARCHAR NOT NULL, state VARCHAR NOT NULL, response_body TEXT)"
        )

    project_root = __file__.replace("\\", "/").split("/tests/")[0]
    config = Config(f"{project_root}/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    command.stamp(config, "0001_initial_core")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    mandate_columns = {column["name"] for column in inspector.get_columns("mandates")}
    assert {"principal_display_name", "allowed_merchant_ids"} <= mandate_columns
    assert any(
        constraint["name"] == "reservation_mandate_transaction"
        for constraint in inspector.get_unique_constraints("reservations")
    )
    assert any(
        constraint["name"] == "idempotency_scope_key"
        for constraint in inspector.get_unique_constraints("idempotency_records")
    )
    idempotency_columns = {column["name"] for column in inspector.get_columns("idempotency_records")}
    assert "retained_until" in idempotency_columns
    assert "mandate_locks" in inspector.get_table_names()


def test_upgrade_from_0002_retains_existing_idempotency_records(tmp_path):
    """A database at the immediately preceding revision must upgrade without a reset."""
    database_path = tmp_path / "aval-0002.db"
    project_root = __file__.replace("\\", "/").split("/tests/")[0]
    config = Config(f"{project_root}/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    command.upgrade(config, "0002_authorization_hardening")
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            idempotency_records.insert().values(
                id="idem-existing", scope="capture", idempotency_key="existing-key",
                request_hash="hash", state="COMPLETED", response_body="{}",
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(
            select(idempotency_records.c.retained_until).where(idempotency_records.c.id == "idem-existing")
        ).scalar_one() is not None


def test_core_does_not_create_schema_for_an_explicit_persistent_engine(tmp_path):
    """Removing Alembic must leave an externally managed database unmigrated."""
    engine = create_sqlite_engine(tmp_path / "unmigrated.db")

    AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC), engine=engine)

    assert "mandates" not in inspect(engine).get_table_names()

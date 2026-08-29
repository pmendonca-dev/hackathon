from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.models import idempotency_records, metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


def test_idempotency_record_is_retained_for_at_least_twenty_four_hours(tmp_path):
    """Removing the retention deadline would allow a retry to become a second capture."""
    engine = create_sqlite_engine(tmp_path / "retention.db")
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)

    run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).get_or_claim(
            "capture", "retry-key", "request-hash", now=claimed_at
        ),
    )

    with engine.connect() as connection:
        retained_until = connection.execute(
            select(idempotency_records.c.retained_until).where(
                idempotency_records.c.scope == "capture",
                idempotency_records.c.idempotency_key == "retry-key",
            )
        ).scalar_one()

    assert retained_until.replace(tzinfo=UTC) >= claimed_at + timedelta(hours=24)

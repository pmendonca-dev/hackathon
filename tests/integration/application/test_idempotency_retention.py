from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def _completed_record(engine, *, claimed_at: datetime, key: str = "retry-key") -> None:
    """Persist a real completed response without relying on a test-only repository hook."""
    def write(connection) -> None:
        repository = SqliteIdempotencyRepository(connection)
        assert repository.get_or_claim("capture", key, "request-hash", now=claimed_at).state == "CLAIMED"
        repository.complete("capture", key, '{"status":"settled"}')

    run_in_write_transaction(engine, write)


def _record_exists(engine, key: str) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            select(idempotency_records.c.id).where(
                idempotency_records.c.scope == "capture",
                idempotency_records.c.idempotency_key == key,
            )
        ).scalar_one_or_none() is not None


def test_purge_keeps_completed_record_before_the_twenty_four_hour_deadline(tmp_path):
    """Deleting early would let a legitimate retry execute a second side effect."""
    engine = create_sqlite_engine(tmp_path / "retention.db")
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)
    _completed_record(engine, claimed_at=claimed_at)

    removed = run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).purge_expired(
            now=claimed_at + timedelta(hours=23, minutes=59, seconds=59)
        ),
    )

    assert removed == 0
    assert _record_exists(engine, "retry-key")


def test_purge_removes_completed_record_when_the_retention_deadline_arrives(tmp_path):
    """A completed response beyond its explicit window must not accumulate forever."""
    engine = create_sqlite_engine(tmp_path / "retention.db")
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)
    _completed_record(engine, claimed_at=claimed_at)

    removed = run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).purge_expired(
            now=claimed_at + timedelta(hours=24)
        ),
    )

    assert removed == 1
    assert not _record_exists(engine, "retry-key")


def test_purge_never_removes_an_expired_in_flight_claim(tmp_path):
    """An unfinished side effect must stay protected even when its initial window elapsed."""
    engine = create_sqlite_engine(tmp_path / "retention.db")
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)
    run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).get_or_claim(
            "capture", "in-flight-key", "request-hash", now=claimed_at
        ),
    )

    removed = run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).purge_expired(
            now=claimed_at + timedelta(days=2)
        ),
    )

    assert removed == 0
    assert _record_exists(engine, "in-flight-key")


def test_completed_replay_keeps_its_original_response_inside_the_retention_window(tmp_path):
    """A purge must not erase the durable response that makes a retry safe."""
    engine = create_sqlite_engine(tmp_path / "retention.db")
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)
    _completed_record(engine, claimed_at=claimed_at)

    removed = run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).purge_expired(
            now=claimed_at + timedelta(hours=23)
        ),
    )

    replay = run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).get_or_claim(
            "capture", "retry-key", "request-hash", now=claimed_at + timedelta(hours=23)
        ),
    )

    assert removed == 0
    assert replay.state == "REPLAY"
    assert replay.response_body == '{"status":"settled"}'


def test_explicit_purge_command_prints_only_the_removed_count(tmp_path):
    """An operator command must have an auditable, payload-free result."""
    database = tmp_path / "retention.db"
    engine = create_sqlite_engine(database)
    metadata.create_all(engine)
    claimed_at = datetime(2026, 8, 29, tzinfo=UTC)
    _completed_record(engine, claimed_at=claimed_at)
    script = Path(__file__).parents[3] / "scripts" / "purge_idempotency_records.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--database",
            str(database),
            "--at",
            (claimed_at + timedelta(days=2)).isoformat(),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "1\n"
    assert completed.stderr == ""

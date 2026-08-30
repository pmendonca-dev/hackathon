"""Explicit, payload-free maintenance for expired idempotency records."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("--at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--at must include a UTC offset")
    return parsed.astimezone(UTC)


def purge(database: Path, *, now: datetime) -> int:
    """Run one caller-selected purge and return only its deleted-record count."""
    engine = create_sqlite_engine(database)
    return run_in_write_transaction(
        engine,
        lambda connection: SqliteIdempotencyRepository(connection).purge_expired(now=now),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--at", required=True, type=_utc_timestamp)
    arguments = parser.parse_args(argv)
    print(purge(arguments.database, now=arguments.at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

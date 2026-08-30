from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select

from aval.infrastructure.sqlite.models import browser_ui_sessions, metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.infrastructure.sqlite.ui_session_repository import (
    SqliteUiSessionRepository,
    UiSessionRecord,
)


def _record(*, expires_at: datetime, revoked_at: datetime | None = None) -> UiSessionRecord:
    return UiSessionRecord(
        id="uis_01",
        token_hash="token-sha256-only",
        csrf_hash="csrf-sha256-only",
        role="merchant",
        merchant_id="merchant_01",
        issued_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _repository(engine):
    return lambda operation: run_in_write_transaction(
        engine, lambda connection: operation(SqliteUiSessionRepository(connection))
    )


def test_active_session_requires_matching_token_hash_and_unexpired_record() -> None:
    engine = create_engine("sqlite+pysqlite://")
    metadata.create_all(engine)
    repository = _repository(engine)
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    repository(lambda store: store.create(_record(expires_at=now + timedelta(minutes=30))))

    active = repository(lambda store: store.get_active_by_token_hash("token-sha256-only", now))
    missing = repository(lambda store: store.get_active_by_token_hash("another-hash", now))

    assert active is not None
    assert active.id == "uis_01"
    assert missing is None


def test_revoked_or_expired_session_is_not_returned() -> None:
    engine = create_engine("sqlite+pysqlite://")
    metadata.create_all(engine)
    repository = _repository(engine)
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    repository(lambda store: store.create(_record(expires_at=now + timedelta(minutes=30))))

    repository(lambda store: store.revoke("uis_01", now))
    revoked = repository(lambda store: store.get_active_by_token_hash("token-sha256-only", now))
    expired = repository(
        lambda store: store.get_active_by_token_hash("token-sha256-only", now + timedelta(hours=1))
    )

    assert revoked is None
    assert expired is None


def test_csrf_rotation_invalidates_the_previous_hash_and_never_persists_plaintext() -> None:
    engine = create_engine("sqlite+pysqlite://")
    metadata.create_all(engine)
    repository = _repository(engine)
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    repository(lambda store: store.create(_record(expires_at=now + timedelta(minutes=30))))
    repository(lambda store: store.rotate_csrf("uis_01", "rotated-csrf-sha256-only"))

    old_matches = repository(
        lambda store: store.matches_active_csrf("uis_01", "csrf-sha256-only", now)
    )
    new_matches = repository(
        lambda store: store.matches_active_csrf("uis_01", "rotated-csrf-sha256-only", now)
    )
    with engine.connect() as connection:
        stored = connection.execute(select(browser_ui_sessions.c.token_hash, browser_ui_sessions.c.csrf_hash)).one()

    assert old_matches is False
    assert new_matches is True
    assert stored == ("token-sha256-only", "rotated-csrf-sha256-only")

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select

from aval.application.services.ui_sessions import (
    UiLocalCredentials,
    UiSessionError,
    UiSessionService,
)
from aval.infrastructure.sqlite.models import browser_ui_sessions, metadata


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _service(clock: MutableClock) -> tuple[UiSessionService, object]:
    engine = create_engine("sqlite+pysqlite://")
    metadata.create_all(engine)
    return (
        UiSessionService(
            engine=engine,
            clock=clock,
            credentials=UiLocalCredentials(merchant="merchant-secret"),
            ttl=timedelta(minutes=30),
        ),
        engine,
    )


def test_login_issues_opaque_cookie_and_csrf_without_persisting_plaintext() -> None:
    clock = MutableClock()
    service, engine = _service(clock)

    issued = service.login("merchant", "merchant-secret")
    principal = service.authenticate(issued.cookie_value)
    with engine.connect() as connection:
        stored = connection.execute(select(browser_ui_sessions)).mappings().one()

    assert issued.cookie_value != issued.csrf_token
    assert principal.role == "merchant"
    assert principal.merchant_id == "merchant_01"
    assert issued.cookie_value not in str(dict(stored))
    assert issued.csrf_token not in str(dict(stored))
    assert stored["token_hash"] != issued.cookie_value
    assert stored["csrf_hash"] != issued.csrf_token


def test_expired_session_returns_ui_session_required() -> None:
    clock = MutableClock()
    service, _ = _service(clock)
    issued = service.login("merchant", "merchant-secret")
    clock.now = clock.now + timedelta(minutes=31)

    with pytest.raises(UiSessionError, match="ui_session_required"):
        service.authenticate(issued.cookie_value)


def test_mutation_with_wrong_csrf_returns_csrf_invalid() -> None:
    clock = MutableClock()
    service, _ = _service(clock)
    issued = service.login("merchant", "merchant-secret")
    principal = service.authenticate(issued.cookie_value)

    with pytest.raises(UiSessionError, match="csrf_invalid"):
        service.validate_csrf(principal, "changed-csrf")


def test_missing_role_credential_never_mints_a_fallback() -> None:
    clock = MutableClock()
    service, _ = _service(clock)

    with pytest.raises(UiSessionError, match="ui_login_invalid"):
        service.login("holder", "any-value")

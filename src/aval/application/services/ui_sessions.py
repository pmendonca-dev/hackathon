from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine

from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.infrastructure.sqlite.ui_session_repository import (
    SqliteUiSessionRepository,
    UiSessionRecord,
)


UI_ROLES = frozenset({"merchant", "holder", "auditor", "operator"})
MERCHANT_SCOPE = "merchant_01"


class UiSessionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UiLocalCredentials:
    """Explicit local credentials. An unset value disables that role."""

    merchant: str | None = None
    holder: str | None = None
    auditor: str | None = None
    operator: str | None = None

    @classmethod
    def from_environment(cls) -> "UiLocalCredentials":
        return cls(
            merchant=_environment_secret("AVAL_UI_MERCHANT_CREDENTIAL"),
            holder=_environment_secret("AVAL_UI_HOLDER_CREDENTIAL"),
            auditor=_environment_secret("AVAL_UI_AUDITOR_CREDENTIAL"),
            operator=_environment_secret("AVAL_UI_OPERATOR_CREDENTIAL"),
        )

    def for_role(self, role: str) -> str | None:
        return getattr(self, role, None) if role in UI_ROLES else None


def _environment_secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class IssuedUiSession:
    """Bearer values exist only between successful login and the HTTP response."""

    cookie_value: str
    csrf_token: str
    role: str
    expires_at: datetime


@dataclass(frozen=True)
class UiPrincipal:
    """Internal authenticated identity; it deliberately holds no bearer credential."""

    session_id: str
    role: str
    merchant_id: str | None


class UiSessionService:
    def __init__(
        self,
        *,
        engine: Engine,
        clock: Callable[[], datetime],
        credentials: UiLocalCredentials,
        ttl: timedelta = timedelta(hours=8),
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._credentials = credentials
        self._ttl = ttl

    def login(self, role: str, credential: str) -> IssuedUiSession:
        configured = self._credentials.for_role(role)
        if configured is None or not isinstance(credential, str) or not hmac.compare_digest(
            configured, credential
        ):
            raise UiSessionError("ui_login_invalid")
        now = self._clock()
        cookie_value = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        issued = IssuedUiSession(
            cookie_value=cookie_value,
            csrf_token=csrf_token,
            role=role,
            expires_at=now + self._ttl,
        )
        record = UiSessionRecord(
            id=f"uis_{uuid4().hex}",
            token_hash=self._hash(cookie_value),
            csrf_hash=self._hash(csrf_token),
            role=role,
            merchant_id=MERCHANT_SCOPE if role == "merchant" else None,
            issued_at=now,
            expires_at=issued.expires_at,
            revoked_at=None,
        )
        run_in_write_transaction(
            self._engine,
            lambda connection: SqliteUiSessionRepository(connection).create(record),
        )
        return issued

    def authenticate(self, cookie_value: str | None) -> UiPrincipal:
        if not cookie_value:
            raise UiSessionError("ui_session_required")
        with self._engine.connect() as connection:
            record = SqliteUiSessionRepository(connection).get_active_by_token_hash(
                self._hash(cookie_value), self._clock()
            )
        if record is None:
            raise UiSessionError("ui_session_required")
        return UiPrincipal(record.id, record.role, record.merchant_id)

    def validate_csrf(self, principal: UiPrincipal, csrf_value: str | None) -> None:
        if not csrf_value:
            raise UiSessionError("csrf_invalid")
        with self._engine.connect() as connection:
            valid = SqliteUiSessionRepository(connection).matches_active_csrf(
                principal.session_id, self._hash(csrf_value), self._clock()
            )
        if not valid:
            raise UiSessionError("csrf_invalid")

    def logout(self, principal: UiPrincipal) -> None:
        run_in_write_transaction(
            self._engine,
            lambda connection: SqliteUiSessionRepository(connection).revoke(
                principal.session_id, self._clock()
            ),
        )

    @property
    def ttl_seconds(self) -> int:
        return max(0, int(self._ttl.total_seconds()))

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

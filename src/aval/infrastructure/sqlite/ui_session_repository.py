from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, select, update

from aval.infrastructure.sqlite.models import browser_ui_sessions


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class UiSessionRecord:
    """A durable browser session containing hashes, never bearer values."""

    id: str
    token_hash: str
    csrf_hash: str
    role: str
    merchant_id: str | None
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class SqliteUiSessionRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, record: UiSessionRecord) -> None:
        self._connection.execute(
            browser_ui_sessions.insert().values(
                id=record.id,
                token_hash=record.token_hash,
                csrf_hash=record.csrf_hash,
                role=record.role,
                merchant_id=record.merchant_id,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
            )
        )

    def get_active_by_token_hash(self, token_hash: str, now: datetime) -> UiSessionRecord | None:
        row = self._connection.execute(
            select(browser_ui_sessions).where(browser_ui_sessions.c.token_hash == token_hash)
        ).mappings().one_or_none()
        if row is None or row["revoked_at"] is not None or _aware(row["expires_at"]) <= now:
            return None
        return self._to_record(row)

    def revoke(self, session_id: str, now: datetime) -> None:
        self._connection.execute(
            update(browser_ui_sessions)
            .where(browser_ui_sessions.c.id == session_id, browser_ui_sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def rotate_csrf(self, session_id: str, csrf_hash: str) -> None:
        self._connection.execute(
            update(browser_ui_sessions)
            .where(browser_ui_sessions.c.id == session_id)
            .values(csrf_hash=csrf_hash)
        )

    def matches_active_csrf(self, session_id: str, csrf_hash: str, now: datetime) -> bool:
        row = self._connection.execute(
            select(browser_ui_sessions.c.csrf_hash, browser_ui_sessions.c.expires_at, browser_ui_sessions.c.revoked_at)
            .where(browser_ui_sessions.c.id == session_id)
        ).mappings().one_or_none()
        return bool(
            row is not None
            and row["revoked_at"] is None
            and _aware(row["expires_at"]) > now
            and hmac.compare_digest(str(row["csrf_hash"]), csrf_hash)
        )

    @staticmethod
    def _to_record(row) -> UiSessionRecord:
        revoked_at = row["revoked_at"]
        return UiSessionRecord(
            id=row["id"],
            token_hash=row["token_hash"],
            csrf_hash=row["csrf_hash"],
            role=row["role"],
            merchant_id=row["merchant_id"],
            issued_at=_aware(row["issued_at"]),
            expires_at=_aware(row["expires_at"]),
            revoked_at=None if revoked_at is None else _aware(revoked_at),
        )

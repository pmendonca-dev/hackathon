from __future__ import annotations

from sqlalchemy import Connection, update

from aval.infrastructure.sqlite.models import capture_attempts


class SqliteCaptureRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, *, attempt_id: str, reservation_id: str, idempotency_key: str) -> None:
        self._connection.execute(capture_attempts.insert().values(
            id=attempt_id, reservation_id=reservation_id, idempotency_key=idempotency_key, status="PENDING"
        ))

    def complete(self, attempt_id: str, *, approved: bool, reference: str | None) -> None:
        self._connection.execute(update(capture_attempts).where(capture_attempts.c.id == attempt_id).values(
            status="SETTLED" if approved else "DECLINED", settlement_reference=reference
        ))

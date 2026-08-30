from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, delete, select, update
from sqlalchemy.exc import IntegrityError

from aval.infrastructure.sqlite.models import idempotency_records


@dataclass(frozen=True)
class IdempotencyClaim:
    state: str
    response_body: str | None = None


class SqliteIdempotencyRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_or_claim(
        self,
        scope: str,
        key: str,
        request_hash: str,
        *,
        now: datetime | None = None,
    ) -> IdempotencyClaim:
        claimed_at = now or datetime.now(UTC)
        row = self._connection.execute(
            select(idempotency_records).where(idempotency_records.c.scope == scope, idempotency_records.c.idempotency_key == key)
        ).mappings().one_or_none()
        if row is None:
            self._connection.execute(idempotency_records.insert().values(
                id=f"idem_{scope}_{key}", scope=scope, idempotency_key=key, request_hash=request_hash,
                state="IN_FLIGHT", retained_until=claimed_at + timedelta(hours=24),
            ))
            return IdempotencyClaim("CLAIMED")
        if row["request_hash"] != request_hash:
            return IdempotencyClaim("MISMATCH")
        if row["state"] == "IN_FLIGHT":
            return IdempotencyClaim("IN_FLIGHT")
        return IdempotencyClaim("REPLAY", row["response_body"])

    def complete(self, scope: str, key: str, response_body: str) -> None:
        self._connection.execute(update(idempotency_records).where(
            idempotency_records.c.scope == scope, idempotency_records.c.idempotency_key == key
        ).values(state="COMPLETED", response_body=response_body))

    def purge_expired(self, *, now: datetime) -> int:
        """Delete only completed responses whose 24-hour replay window has ended."""
        result = self._connection.execute(
            delete(idempotency_records).where(
                idempotency_records.c.state == "COMPLETED",
                idempotency_records.c.retained_until <= now,
            )
        )
        return int(result.rowcount)

    def consume_once(self, scope: str, key: str) -> bool:
        try:
            self._connection.execute(idempotency_records.insert().values(
                id=f"idem_{scope}_{key}", scope=scope, idempotency_key=key,
                request_hash=key, state="COMPLETED", response_body="consumed",
                retained_until=datetime.now(UTC) + timedelta(hours=24),
            ))
        except IntegrityError:
            return False
        return True

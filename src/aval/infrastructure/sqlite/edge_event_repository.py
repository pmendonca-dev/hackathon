"""The outbox, as rows.

Reading does not deliver. Only an explicit acknowledgement from Computer A does, and it
is idempotent — A is allowed to retry an ack it is no longer sure it sent, because the
alternative is A choosing between telling someone twice and never telling them at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, select, update

from aval.infrastructure.sqlite.models import edge_events


class EdgeEvent:
    """One thing B has to tell A."""

    __slots__ = ("id", "principal_id", "event_type", "payload", "created_at", "delivered_at")

    def __init__(
        self,
        *,
        id: int,
        principal_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: datetime,
        delivered_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.principal_id = principal_id
        self.event_type = event_type
        self.payload = payload
        self.created_at = created_at
        self.delivered_at = delivered_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "principal_id": self.principal_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqliteEdgeEventRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append(
        self,
        *,
        principal_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        self._connection.execute(
            edge_events.insert().values(
                principal_id=principal_id,
                event_type=event_type,
                # Stored canonical-ish and read back whole. The column is the contract
                # with Computer A, and A parses it without knowing this schema.
                payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                created_at=created_at,
                delivered_at=None,
            )
        )

    def undelivered_after(self, *, after: int | None = None, limit: int = 50) -> list[EdgeEvent]:
        """What A has not confirmed, in the order it happened.

        Both filters are needed. `delivered_at IS NULL` is what makes a lost response
        harmless; the cursor is what stops one poll from re-reading rows A is still
        working through in the same batch.
        """
        query = select(edge_events).where(edge_events.c.delivered_at.is_(None))
        if after is not None:
            query = query.where(edge_events.c.id > after)
        rows = (
            self._connection.execute(query.order_by(edge_events.c.id).limit(limit))
            .mappings()
            .all()
        )
        return [self._to_event(row) for row in rows]

    def mark_delivered(self, event_id: int, *, delivered_at: datetime) -> None:
        """Idempotent by construction: only an undelivered row is touched, and an id
        that does not exist updates nothing without complaining."""
        self._connection.execute(
            update(edge_events)
            .where(edge_events.c.id == event_id, edge_events.c.delivered_at.is_(None))
            .values(delivered_at=delivered_at)
        )

    @staticmethod
    def _to_event(row) -> EdgeEvent:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        return EdgeEvent(
            id=row["id"],
            principal_id=row["principal_id"],
            event_type=row["event_type"],
            payload=payload if isinstance(payload, dict) else {},
            created_at=_aware(row["created_at"]),
            delivered_at=_aware(row["delivered_at"]),
        )

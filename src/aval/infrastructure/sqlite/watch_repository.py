"""Standing orders, kept where a restart cannot lose them.

An agent that forgets what it was watching the moment the process dies is not watching
anything. The row outlives the bot, the API and the conversation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection, select, update

from aval.domain.entities import Watch
from aval.domain.enums import WatchStatus
from aval.infrastructure.sqlite.models import agent_watches


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqliteWatchRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, watch: Watch) -> None:
        self._connection.execute(
            agent_watches.insert().values(
                id=watch.id,
                mandate_id=watch.mandate_id,
                instruction=watch.instruction,
                status=watch.status.value,
                outcome=watch.outcome,
                settlement_reference=watch.settlement_reference,
                created_at=watch.created_at,
                expires_at=watch.expires_at,
                closed_at=watch.closed_at,
            )
        )

    def get(self, watch_id: str) -> Watch | None:
        row = self._connection.execute(
            select(agent_watches).where(agent_watches.c.id == watch_id)
        ).mappings().one_or_none()
        return None if row is None else self._to_watch(row)

    def for_mandate(self, mandate_id: str) -> list[Watch]:
        rows = self._connection.execute(
            select(agent_watches)
            .where(agent_watches.c.mandate_id == mandate_id)
            .order_by(agent_watches.c.created_at)
        ).mappings().all()
        return [self._to_watch(row) for row in rows]

    def open_for_mandate(self, mandate_id: str) -> list[Watch]:
        return [
            watch
            for watch in self.for_mandate(mandate_id)
            if watch.status is WatchStatus.OPEN
        ]

    def mandates_with_open_watches(self) -> list[str]:
        """Which mandates still have something being watched for.

        The only query in this repository that is not scoped to one mandate, and it
        deliberately returns ids and nothing else: it exists so a scheduler knows where
        to look, and a scheduler has no business reading what anyone asked to buy.
        """
        rows = self._connection.execute(
            select(agent_watches.c.mandate_id)
            .where(agent_watches.c.status == WatchStatus.OPEN.value)
            .distinct()
            .order_by(agent_watches.c.mandate_id)
        ).all()
        return [row[0] for row in rows]

    def close(
        self,
        watch_id: str,
        *,
        status: WatchStatus,
        outcome: str | None,
        settlement_reference: str | None,
        closed_at: datetime,
    ) -> None:
        self._connection.execute(
            update(agent_watches)
            .where(
                agent_watches.c.id == watch_id,
                # Only an open watch closes. Two ticks racing cannot both spend it.
                agent_watches.c.status == WatchStatus.OPEN.value,
            )
            .values(
                status=status.value,
                outcome=outcome,
                settlement_reference=settlement_reference,
                closed_at=closed_at,
            )
        )

    @staticmethod
    def _to_watch(row) -> Watch:
        return Watch(
            id=row["id"],
            mandate_id=row["mandate_id"],
            instruction=row["instruction"],
            created_at=_aware(row["created_at"]),
            expires_at=_aware(row["expires_at"]),
            status=WatchStatus(row["status"]),
            outcome=row["outcome"],
            settlement_reference=row["settlement_reference"],
            closed_at=_aware(row["closed_at"]),
        )

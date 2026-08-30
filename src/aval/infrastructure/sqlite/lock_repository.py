from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection
from sqlalchemy.dialects.sqlite import insert

from aval.infrastructure.sqlite.models import mandate_locks


class SqliteMandateLockRepository:
    """Acquires the durable resource shared by capture and signed revocation."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def acquire(self, mandate_id: str, *, touched_at: datetime) -> None:
        statement = insert(mandate_locks).values(mandate_id=mandate_id, touched_at=touched_at)
        self._connection.execute(
            statement.on_conflict_do_update(
                index_elements=[mandate_locks.c.mandate_id],
                set_={"touched_at": touched_at},
            )
        )

from __future__ import annotations

from sqlalchemy import Connection

from aval.domain.entities import AuditEvent
from aval.infrastructure.sqlite.models import audit_events


class SqliteAuditRepository:
    """Append-only audit writer used only by the authorization core."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append(self, event: AuditEvent) -> None:
        self._connection.execute(audit_events.insert().values(
            id=event.id, mandate_id=event.mandate_id, event_type=event.event_type,
            human_summary=event.human_summary, evidence_id=event.evidence_id, occurred_at=event.occurred_at,
        ))

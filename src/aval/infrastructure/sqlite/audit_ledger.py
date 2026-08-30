"""The audit trail, written as a hash chain.

Each event canonicalises itself with RFC 8785 and hashes the digest of the event
before it. Editing any row after the fact breaks its own digest and, with it, every
link that follows — so the trail is not merely a log the operator promises not to
edit, it is a log an auditor can check without trusting the operator.

The chain is scoped per mandate. That is deliberate: an auditor can verify one
mandate end to end without being handed anyone else's purchases.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, select

from aval.infrastructure.sqlite.models import audit_events, evidence
from aval.security.jcs import canonicalize

GENESIS_DIGEST = "0" * 64


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    mandate_id: str
    event_type: str
    human_summary: str
    actor: str
    detail: Mapping[str, Any]
    occurred_at: datetime
    sha256: str
    previous_sha256: str
    canonical_payload: str

    @property
    def recomputed_sha256(self) -> str:
        """Hash the stored bytes exactly as they sit on disk, not a re-serialisation of
        them. A re-serialisation could quietly repair the very tampering we look for."""
        return hashlib.sha256(self.canonical_payload.encode("utf-8")).hexdigest()


class SqliteAuditLedger:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _head(self, mandate_id: str) -> tuple[int, str]:
        row = self._connection.execute(
            select(audit_events.c.sequence, evidence.c.sha256)
            .join(evidence, audit_events.c.evidence_id == evidence.c.id)
            .where(audit_events.c.mandate_id == mandate_id)
            .order_by(audit_events.c.sequence.desc())
            .limit(1)
        ).first()
        return (0, GENESIS_DIGEST) if row is None else (int(row[0]), str(row[1]))

    def append(
        self,
        *,
        mandate_id: str,
        event_type: str,
        human_summary: str,
        actor: str,
        detail: Mapping[str, Any],
        occurred_at: datetime,
    ) -> LedgerEntry:
        last_sequence, previous = self._head(mandate_id)
        sequence = last_sequence + 1
        record = {
            "sequence": sequence,
            "mandate_id": mandate_id,
            "event_type": event_type,
            "actor": actor,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "previous_sha256": previous,
            "detail": dict(detail),
        }
        canonical = canonicalize(record)
        digest = hashlib.sha256(canonical).hexdigest()
        evidence_id = f"evd_{uuid4().hex}"
        self._connection.execute(
            evidence.insert().values(
                id=evidence_id,
                kind=event_type,
                origin=actor,
                sha256=digest,
                payload=canonical.decode("utf-8"),
            )
        )
        self._connection.execute(
            audit_events.insert().values(
                id=f"aud_{uuid4().hex}",
                mandate_id=mandate_id,
                event_type=event_type,
                human_summary=human_summary,
                evidence_id=evidence_id,
                occurred_at=occurred_at,
                sequence=sequence,
            )
        )
        return LedgerEntry(
            sequence=sequence,
            mandate_id=mandate_id,
            event_type=event_type,
            human_summary=human_summary,
            actor=actor,
            detail=dict(detail),
            occurred_at=occurred_at,
            sha256=digest,
            previous_sha256=previous,
            canonical_payload=canonical.decode("utf-8"),
        )

    def timeline_for(self, mandate_id: str) -> list[LedgerEntry]:
        rows = self._connection.execute(
            self._joined().where(audit_events.c.mandate_id == mandate_id)
            .order_by(audit_events.c.sequence)
        ).mappings().all()
        return [self._to_entry(row) for row in rows]

    def entries_for_merchant(self, merchant_id: str) -> list[LedgerEntry]:
        """Ordered by wall clock, then by the mandate's own sequence to break ties. The
        chain itself is per mandate, so this ordering is presentational only."""
        rows = self._connection.execute(
            self._joined().order_by(audit_events.c.occurred_at, audit_events.c.sequence)
        ).mappings().all()
        entries = (self._to_entry(row) for row in rows)
        return [entry for entry in entries if entry.detail.get("merchant_id") == merchant_id]

    @staticmethod
    def _joined():
        return select(
            audit_events.c.sequence,
            audit_events.c.mandate_id,
            audit_events.c.event_type,
            audit_events.c.human_summary,
            audit_events.c.occurred_at,
            evidence.c.sha256,
            evidence.c.origin,
            evidence.c.payload,
        ).join(evidence, audit_events.c.evidence_id == evidence.c.id)

    @staticmethod
    def _to_entry(row) -> LedgerEntry:
        record = json.loads(row["payload"])
        occurred_at = row["occurred_at"]
        return LedgerEntry(
            sequence=int(row["sequence"]),
            mandate_id=row["mandate_id"],
            event_type=row["event_type"],
            human_summary=row["human_summary"],
            actor=row["origin"],
            detail=record.get("detail", {}),
            occurred_at=occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC),
            sha256=row["sha256"],
            previous_sha256=record.get("previous_sha256", ""),
            canonical_payload=row["payload"],
        )


def verify_chain(entries: list[LedgerEntry]) -> tuple[bool, int | None]:
    """Walk the chain. Returns the sequence number of the first event that fails."""
    previous = GENESIS_DIGEST
    for entry in entries:
        if entry.recomputed_sha256 != entry.sha256 or entry.previous_sha256 != previous:
            return False, entry.sequence
        previous = entry.sha256
    return True, None

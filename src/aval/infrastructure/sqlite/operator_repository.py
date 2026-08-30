"""Operator sessions, and the chained journal of what an operator did.

Two small stores with one purpose between them: make *operating the instance* as
readable as *spending the money* already was. The holder proves authority with a
signature; the operator has no signature to give, so what is recorded instead is a
tamper-evident sequence of actions and the session that took them.

Nothing here can authorize a purchase, raise a limit or approve an escalation. That is
the point — the asymmetry is the thesis, and these tables must never become a way
around it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, select, update

from aval.infrastructure.sqlite.models import operator_journal, operator_sessions
from aval.security.jcs import canonicalize

GENESIS_DIGEST = "0" * 64


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedOperatorSession:
    id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class JournalEntry:
    sequence: int
    action: str
    actor: str
    detail: dict[str, Any]
    occurred_at: datetime
    sha256: str
    previous_sha256: str
    canonical_payload: str

    @property
    def recomputed_sha256(self) -> str:
        """Hash the bytes as they sit on disk. Re-serialising first could repair the
        very edit this exists to catch."""
        return hashlib.sha256(self.canonical_payload.encode("utf-8")).hexdigest()


class SqliteOperatorSessions:
    """Issue, authenticate and end the credential the console holds."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def issue(self, *, now: datetime, ttl_seconds: int) -> IssuedOperatorSession:
        session_id = f"ops_{uuid4().hex}"
        # The token is returned once and never stored: what is kept is its digest, so
        # a copy of this database is not a set of working operator credentials.
        token = f"{session_id}.{secrets.token_urlsafe(32)}"
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=now.tzinfo)
        self._connection.execute(
            operator_sessions.insert().values(
                id=session_id,
                token_hash=_hash(token),
                issued_at=now,
                expires_at=expires_at,
            )
        )
        return IssuedOperatorSession(id=session_id, token=token, expires_at=expires_at)

    def authenticate(self, token: str, *, now: datetime) -> str:
        """The session id, or a reason code as a ValueError.

        Unknown and expired are answered differently on purpose: an operator whose
        session ran out needs to be told to open another one, and neither answer tells
        an outsider anything they could not learn by trying.
        """
        row = self._connection.execute(
            select(operator_sessions.c.id, operator_sessions.c.expires_at, operator_sessions.c.revoked_at)
            .where(operator_sessions.c.token_hash == _hash(token))
        ).mappings().first()
        if row is None or row["revoked_at"] is not None:
            raise ValueError("operator_session_invalid")
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)
        if expires_at <= now:
            raise ValueError("operator_session_expired")
        return str(row["id"])

    def revoke(self, session_id: str, *, now: datetime) -> None:
        self._connection.execute(
            update(operator_sessions)
            .where(operator_sessions.c.id == session_id, operator_sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class SqliteOperatorJournal:
    """The chain of operator actions, written and walked with the ledger's discipline."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _head(self) -> tuple[int, str]:
        row = self._connection.execute(
            select(operator_journal.c.sequence, operator_journal.c.sha256)
            .order_by(operator_journal.c.sequence.desc())
            .limit(1)
        ).first()
        return (0, GENESIS_DIGEST) if row is None else (int(row[0]), str(row[1]))

    def append(
        self, *, action: str, actor: str, detail: dict[str, Any], occurred_at: datetime
    ) -> JournalEntry:
        last_sequence, previous = self._head()
        sequence = last_sequence + 1
        record = {
            "sequence": sequence,
            "action": action,
            "actor": actor,
            "detail": detail,
            "occurred_at": occurred_at.isoformat(),
            "previous_sha256": previous,
        }
        canonical = canonicalize(record).decode("utf-8")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self._connection.execute(
            operator_journal.insert().values(
                id=f"opj_{uuid4().hex}",
                sequence=sequence,
                action=action,
                actor=actor,
                detail=json.dumps(detail, separators=(",", ":")),
                occurred_at=occurred_at,
                sha256=digest,
                previous_sha256=previous,
                canonical_payload=canonical,
            )
        )
        return JournalEntry(
            sequence=sequence,
            action=action,
            actor=actor,
            detail=detail,
            occurred_at=occurred_at,
            sha256=digest,
            previous_sha256=previous,
            canonical_payload=canonical,
        )

    def entries(self) -> list[JournalEntry]:
        rows = self._connection.execute(
            select(operator_journal).order_by(operator_journal.c.sequence)
        ).mappings().all()
        return [
            JournalEntry(
                sequence=int(row["sequence"]),
                action=str(row["action"]),
                actor=str(row["actor"]),
                detail=json.loads(row["detail"]),
                occurred_at=row["occurred_at"],
                sha256=str(row["sha256"]),
                previous_sha256=str(row["previous_sha256"]),
                canonical_payload=str(row["canonical_payload"]),
            )
            for row in rows
        ]


def verify_journal(entries: list[JournalEntry]) -> tuple[bool, int | None]:
    """Walk the chain, naming the first sequence that does not hold."""
    previous = GENESIS_DIGEST
    for entry in entries:
        if entry.recomputed_sha256 != entry.sha256 or entry.previous_sha256 != previous:
            return False, entry.sequence
        previous = entry.sha256
    return True, None

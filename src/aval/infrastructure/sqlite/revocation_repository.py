from __future__ import annotations

from sqlalchemy import Connection, select

from aval.domain.entities import Revocation
from aval.infrastructure.sqlite.models import revocations


class SqliteRevocationRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def is_revoked(self, mandate_id: str) -> bool:
        return self._connection.execute(
            select(revocations.c.id).where(revocations.c.mandate_id == mandate_id, revocations.c.scope == "mandate").limit(1)
        ).scalar() is not None

    def append(self, revocation: Revocation) -> None:
        self._connection.execute(revocations.insert().values(
            id=revocation.id, mandate_id=revocation.mandate_id, authority_id=revocation.authority_id,
            scope=revocation.scope, reason=revocation.reason, epoch=revocation.epoch,
            signed_jws=revocation.signed_jws, revoked_at=revocation.revoked_at,
        ))

from __future__ import annotations

import json
from datetime import UTC

from sqlalchemy import Connection, select, update

from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import MandateStatus, RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.models import mandates, revocation_authorities


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqliteMandateRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def put(self, mandate: Mandate) -> None:
        values = {
            "principal_id": mandate.principal.id,
            "principal_display_name": mandate.principal.display_name,
            "allowed_merchant_ids": json.dumps(sorted(mandate.allowed_merchant_ids)),
            "status": mandate.status.value,
            "currency": mandate.limit.currency,
            "scale": mandate.limit.scale,
            "limit_minor_units": mandate.limit.minor_units,
            "expires_at": mandate.expires_at,
            "policy_version": mandate.policy_version,
            "revocation_epoch": int(mandate.revocation_metadata.get("epoch", 0)),
            "revocation_metadata": json.dumps(dict(mandate.revocation_metadata)),
        }
        existing = self._connection.execute(select(mandates.c.id).where(mandates.c.id == mandate.id)).scalar()
        if existing:
            self._connection.execute(update(mandates).where(mandates.c.id == mandate.id).values(**values))
            return
        self._connection.execute(mandates.insert().values(id=mandate.id, **values))
        for authority in mandate.authorities:
            self._connection.execute(revocation_authorities.insert().values(
                id=authority.id, mandate_id=mandate.id, role=authority.role.value, kid=authority.kid,
                public_jwk=json.dumps(dict(authority.public_jwk)),
                allowed_scope=json.dumps(sorted(authority.allowed_scopes)),
            ))

    def get(self, mandate_id: str) -> Mandate | None:
        row = self._connection.execute(select(mandates).where(mandates.c.id == mandate_id)).mappings().one_or_none()
        return self._to_mandate(row) if row else None

    def for_authority_kid(self, kid: str) -> list[Mandate]:
        rows = self._connection.execute(
            select(mandates).join(revocation_authorities).where(revocation_authorities.c.kid == kid)
        ).mappings()
        return [self._to_mandate(row) for row in rows]

    def _to_mandate(self, row) -> Mandate:
        authority_rows = self._connection.execute(
            select(revocation_authorities).where(revocation_authorities.c.mandate_id == row["id"])
        ).mappings()
        authorities = tuple(
            RevocationAuthority(
                id=item["id"], kid=item["kid"], role=RevocationRole(item["role"]),
                public_jwk=json.loads(item["public_jwk"]), allowed_scopes=frozenset(json.loads(item["allowed_scope"])),
            )
            for item in authority_rows
        )
        metadata = json.loads(row["revocation_metadata"])
        metadata["epoch"] = row["revocation_epoch"]
        return Mandate(
            id=row["id"], principal=Principal(row["principal_id"], row["principal_display_name"]),
            allowed_merchant_ids=frozenset(json.loads(row["allowed_merchant_ids"])),
            limit=Money(row["limit_minor_units"], row["currency"], row["scale"]),
            expires_at=_aware(row["expires_at"]), policy_version=row["policy_version"],
            revocation_metadata=metadata, authorities=authorities, status=MandateStatus(row["status"]),
        )

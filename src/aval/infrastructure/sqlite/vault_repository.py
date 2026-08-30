from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, select

from aval.domain.money import Money
from aval.infrastructure.sqlite.models import vault_tokens


@dataclass(frozen=True)
class VaultTokenRecord:
    id: str
    mandate_id: str
    checkout_id: str
    merchant_id: str
    max_amount: Money
    expires_at: datetime

    def matches(
        self, *, mandate_id: str, checkout_id: str, merchant_id: str, amount: Money, now: datetime
    ) -> bool:
        return (
            self.mandate_id == mandate_id
            and self.checkout_id == checkout_id
            and self.merchant_id == merchant_id
            and (amount.currency, amount.scale) == (self.max_amount.currency, self.max_amount.scale)
            and 0 < amount.minor_units <= self.max_amount.minor_units
            and now < self.expires_at
        )


class SqliteVaultTokenRepository:
    """Stores only opaque token scope; it never accepts or returns card data."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def put(self, record: VaultTokenRecord) -> None:
        self._connection.execute(
            vault_tokens.insert().values(
                id=record.id,
                mandate_id=record.mandate_id,
                checkout_intent_id=record.checkout_id,
                merchant_id=record.merchant_id,
                max_amount_minor_units=record.max_amount.minor_units,
                currency=record.max_amount.currency,
                scale=record.max_amount.scale,
                expires_at=record.expires_at,
            )
        )

    def get(self, token: str) -> VaultTokenRecord | None:
        row = self._connection.execute(
            select(vault_tokens).where(vault_tokens.c.id == token)
        ).mappings().one_or_none()
        if row is None:
            return None
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return VaultTokenRecord(
            id=row["id"], mandate_id=row["mandate_id"], checkout_id=row["checkout_intent_id"],
            merchant_id=row["merchant_id"],
            max_amount=Money(row["max_amount_minor_units"], row["currency"], row["scale"]),
            expires_at=expires_at,
        )

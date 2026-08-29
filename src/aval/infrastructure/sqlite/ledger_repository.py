from __future__ import annotations

import json

from sqlalchemy import Connection, func, select, update

from aval.domain.entities import Reservation
from aval.domain.enums import ReservationStatus
from aval.domain.money import Money
from aval.infrastructure.sqlite.models import checkout_intents, reservations


class SqliteLedgerRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def spent_for(self, mandate_id: str, unit: Money) -> Money:
        amount = self._connection.execute(
            select(func.coalesce(func.sum(reservations.c.amount_minor_units), 0)).where(
                reservations.c.mandate_id == mandate_id,
                reservations.c.status.in_((ReservationStatus.COMMITTED.value, ReservationStatus.SETTLED.value)),
            )
        ).scalar_one()
        return Money(int(amount), unit.currency, unit.scale)

    def save(self, reservation: Reservation, *, merchant_id: str) -> None:
        existing_checkout = self._connection.execute(
            select(checkout_intents.c.id).where(checkout_intents.c.id == reservation.checkout_intent_id)
        ).scalar()
        if not existing_checkout:
            self._connection.execute(checkout_intents.insert().values(
                id=reservation.checkout_intent_id, mandate_id=reservation.mandate_id, merchant_id=merchant_id,
                total_minor_units=reservation.amount.minor_units, currency=reservation.amount.currency,
                scale=reservation.amount.scale, status="CAPTURING", canonical_payload=json.dumps({"id": reservation.checkout_intent_id}),
            ))
        self._connection.execute(reservations.insert().values(
            id=reservation.id, mandate_id=reservation.mandate_id, checkout_intent_id=reservation.checkout_intent_id,
            amount_minor_units=reservation.amount.minor_units, status=reservation.status.value,
            transaction_hash=reservation.transaction_hash,
        ))

    def update(self, reservation: Reservation) -> None:
        self._connection.execute(update(reservations).where(reservations.c.id == reservation.id).values(
            status=reservation.status.value, transaction_hash=reservation.transaction_hash
        ))

    def find_by_transaction(self, mandate_id: str, transaction_hash: str, unit: Money) -> Reservation | None:
        row = self._connection.execute(select(reservations).where(
            reservations.c.mandate_id == mandate_id, reservations.c.transaction_hash == transaction_hash
        )).mappings().one_or_none()
        if row is None:
            return None
        return Reservation(row["id"], row["mandate_id"], row["checkout_intent_id"], Money(row["amount_minor_units"], unit.currency, unit.scale), ReservationStatus(row["status"]), row["transaction_hash"])

    def get(self, reservation_id: str, unit: Money) -> Reservation | None:
        row = self._connection.execute(select(reservations).where(reservations.c.id == reservation_id)).mappings().one_or_none()
        if row is None:
            return None
        return Reservation(row["id"], row["mandate_id"], row["checkout_intent_id"], Money(row["amount_minor_units"], unit.currency, unit.scale), ReservationStatus(row["status"]), row["transaction_hash"])

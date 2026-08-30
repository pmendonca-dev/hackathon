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

    def live_reservations(self, mandate_id: str) -> int:
        """Reservations holding money right now, waiting on an answer.

        `COMMITTED` and only `COMMITTED`: a settled purchase is finished and a released
        one gave its money back, so neither occupies anything. This is the count that
        an agent looping on an unanswered processor drives upwards without ever
        spending a cent.
        """
        return int(
            self._connection.execute(
                select(func.count())
                .select_from(reservations)
                .where(
                    reservations.c.mandate_id == mandate_id,
                    reservations.c.status == ReservationStatus.COMMITTED.value,
                )
            ).scalar_one()
        )

    def uses_since(self, mandate_id: str, since) -> int:
        """How many times money was actually held for this mandate inside the window.

        Counts commit stamps, not attempts. A reservation the processor released has no
        stamp, so a declined card never eats one of the buyer's allowed uses.
        """
        return int(
            self._connection.execute(
                select(func.count())
                .select_from(reservations)
                .where(
                    reservations.c.mandate_id == mandate_id,
                    reservations.c.committed_at.is_not(None),
                    reservations.c.committed_at >= since,
                )
            ).scalar_one()
        )

    def save(
        self, reservation: Reservation, *, merchant_id: str, canonical_payload: str | None = None
    ) -> None:
        existing_checkout = self._connection.execute(
            select(checkout_intents.c.id).where(checkout_intents.c.id == reservation.checkout_intent_id)
        ).scalar()
        if not existing_checkout:
            self._connection.execute(checkout_intents.insert().values(
                id=reservation.checkout_intent_id, mandate_id=reservation.mandate_id, merchant_id=merchant_id,
                total_minor_units=reservation.amount.minor_units, currency=reservation.amount.currency,
                scale=reservation.amount.scale, status="CAPTURING",
                # The canonical offer when the purchase was bound to one. That is what
                # makes the merchant receipt checkable months later.
                canonical_payload=canonical_payload
                or json.dumps({"id": reservation.checkout_intent_id}),
            ))
        self._connection.execute(reservations.insert().values(
            id=reservation.id, mandate_id=reservation.mandate_id, checkout_intent_id=reservation.checkout_intent_id,
            amount_minor_units=reservation.amount.minor_units, status=reservation.status.value,
            transaction_hash=reservation.transaction_hash,
        ))

    def update(self, reservation: Reservation, *, at=None) -> None:
        # A released reservation gives its transaction slot back. The hash is a claim on
        # the mandate — "this exact purchase is currently in flight or settled" — and a
        # purchase the processor refused is neither. Keeping the claim would mean a
        # declined card could never retry the same basket, and the unique index on
        # (mandate_id, transaction_hash) would refuse the second attempt outright.
        released = reservation.status is ReservationStatus.RELEASED
        values = {
            "status": reservation.status.value,
            "transaction_hash": None if released else reservation.transaction_hash,
        }
        # The commit stamp is what a frequency limit counts. It is written once, when
        # the money is first held, and cleared when the reservation is released — a
        # settlement later must not restamp and move the use into a newer window.
        if released:
            values["committed_at"] = None
        elif at is not None and reservation.status is ReservationStatus.COMMITTED:
            values["committed_at"] = at
        self._connection.execute(
            update(reservations).where(reservations.c.id == reservation.id).values(**values)
        )

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

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, select

from aval.infrastructure.sqlite.models import payment_runtime_captures


@dataclass(frozen=True)
class PersistedRuntimeCapture:
    id: str
    mandate_id: str
    checkout_id: str
    settlement_reference: str
    checkout_receipt: str
    payment_receipt: str


class SqlitePaymentRuntimeRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, capture_id: str) -> PersistedRuntimeCapture | None:
        row = self._connection.execute(select(payment_runtime_captures).where(
            payment_runtime_captures.c.id == capture_id
        )).mappings().one_or_none()
        return None if row is None else PersistedRuntimeCapture(
            id=row["id"], mandate_id=row["mandate_id"], checkout_id=row["checkout_intent_id"],
            settlement_reference=row["settlement_reference"], checkout_receipt=row["checkout_receipt"],
            payment_receipt=row["payment_receipt"],
        )

    def latest_for_mandate(self, mandate_id: str) -> PersistedRuntimeCapture | None:
        row = self._connection.execute(select(payment_runtime_captures).where(
            payment_runtime_captures.c.mandate_id == mandate_id
        ).order_by(payment_runtime_captures.c.id.desc()).limit(1)).mappings().one_or_none()
        return None if row is None else PersistedRuntimeCapture(
            id=row["id"], mandate_id=row["mandate_id"], checkout_id=row["checkout_intent_id"],
            settlement_reference=row["settlement_reference"], checkout_receipt=row["checkout_receipt"],
            payment_receipt=row["payment_receipt"],
        )

    def put(self, capture: PersistedRuntimeCapture) -> None:
        self._connection.execute(payment_runtime_captures.insert().values(
            id=capture.id, mandate_id=capture.mandate_id, checkout_intent_id=capture.checkout_id,
            settlement_reference=capture.settlement_reference,
            checkout_receipt=capture.checkout_receipt, payment_receipt=capture.payment_receipt,
        ))

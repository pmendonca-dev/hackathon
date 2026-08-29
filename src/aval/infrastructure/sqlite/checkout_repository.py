from __future__ import annotations

import json

from sqlalchemy import Engine, select, update

from aval.application.services.checkout import CheckoutCommand, CheckoutSession
from aval.domain.money import Money
from aval.infrastructure.sqlite.models import checkout_intents
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


class SqliteCheckoutRepository:
    """Durable store for the canonical checkout session consumed by UCP/AP2."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, checkout_id: str, session: CheckoutSession) -> None:
        command = session.command
        document = {
            "payload": dict(session.payload),
            "capabilities": sorted(command.negotiated_capabilities),
        }
        values = {
            "mandate_id": command.mandate_id,
            "merchant_id": command.merchant_id,
            "total_minor_units": command.total.minor_units,
            "currency": command.total.currency,
            "scale": command.total.scale,
            "status": str(session.payload["status"]),
            "canonical_payload": json.dumps(document, separators=(",", ":")),
        }

        def persist(connection) -> None:
            existing = connection.execute(
                select(checkout_intents.c.id).where(checkout_intents.c.id == checkout_id)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(checkout_intents.insert().values(id=checkout_id, **values))
            else:
                connection.execute(
                    update(checkout_intents).where(checkout_intents.c.id == checkout_id).values(**values)
                )

        run_in_write_transaction(self._engine, persist)

    def get(self, checkout_id: str) -> CheckoutSession | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(checkout_intents).where(checkout_intents.c.id == checkout_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        document = json.loads(row["canonical_payload"])
        command = CheckoutCommand(
            id=row["id"],
            mandate_id=row["mandate_id"],
            merchant_id=row["merchant_id"],
            total=Money(row["total_minor_units"], row["currency"], row["scale"]),
            line_items=tuple(document["payload"]["line_items"]),
            negotiated_capabilities=frozenset(document["capabilities"]),
        )
        from aval.adapters.ucp.ap2_extension import Ap2CheckoutLock

        return CheckoutSession(document["payload"], Ap2CheckoutLock(command.negotiated_capabilities), command)

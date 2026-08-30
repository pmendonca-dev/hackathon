"""Escalations: the purchases waiting on a person.

The row is the contract between the refusal and the approval. It freezes the exact
purchase that was escalated, so what comes back later can only ever approve *that*.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection, select, update

from aval.domain.entities import Escalation
from aval.domain.enums import EscalationStatus
from aval.domain.money import Money
from aval.infrastructure.sqlite.models import escalations, mandates


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqliteEscalationRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, escalation: Escalation) -> None:
        self._connection.execute(
            escalations.insert().values(
                id=escalation.id,
                mandate_id=escalation.mandate_id,
                checkout_id=escalation.checkout_id,
                merchant_id=escalation.merchant_id,
                category=escalation.category,
                amount_minor_units=escalation.amount.minor_units,
                currency=escalation.amount.currency,
                scale=escalation.amount.scale,
                reason_code=escalation.reason_code,
                status=escalation.status.value,
                agent_id=escalation.agent_id,
                created_at=escalation.created_at,
                expires_at=escalation.expires_at,
                approval_jws=None,
                decided_at=None,
            )
        )

    def get(self, escalation_id: str) -> Escalation | None:
        row = self._connection.execute(
            select(escalations).where(escalations.c.id == escalation_id)
        ).mappings().one_or_none()
        return None if row is None else self._to_escalation(row)

    def find_open_match(
        self, *, mandate_id: str, checkout_id: str, merchant_id: str, amount: Money, reason_code: str
    ) -> Escalation | None:
        """Reuse an identical pending request instead of minting another one.

        An agent that retries the same refused purchase should ping the human once, not
        once per attempt.
        """
        row = self._connection.execute(
            select(escalations).where(
                escalations.c.mandate_id == mandate_id,
                escalations.c.checkout_id == checkout_id,
                escalations.c.merchant_id == merchant_id,
                escalations.c.amount_minor_units == amount.minor_units,
                escalations.c.reason_code == reason_code,
                escalations.c.status == EscalationStatus.OPEN.value,
            )
        ).mappings().first()
        return None if row is None else self._to_escalation(row)

    def open_for_mandate(self, mandate_id: str) -> list[Escalation]:
        rows = self._connection.execute(
            select(escalations)
            .where(
                escalations.c.mandate_id == mandate_id,
                escalations.c.status == EscalationStatus.OPEN.value,
            )
            .order_by(escalations.c.created_at)
        ).mappings().all()
        return [self._to_escalation(row) for row in rows]

    def open_for_principal(self, principal_id: str) -> list[Escalation]:
        """What is waiting on one person, across every mandate they hold.

        The join is the access control: an escalation is reachable only through the
        mandate that owns it, so a caller cannot read a decision waiting on somebody
        else by asking for it in bulk.
        """
        rows = self._connection.execute(
            select(escalations)
            .join(mandates, mandates.c.id == escalations.c.mandate_id)
            .where(
                mandates.c.principal_id == principal_id,
                escalations.c.status == EscalationStatus.OPEN.value,
            )
            .order_by(escalations.c.created_at)
        ).mappings().all()
        return [self._to_escalation(row) for row in rows]

    def mark_decided(
        self, escalation_id: str, *, status: EscalationStatus, approval_jws: str, decided_at: datetime
    ) -> None:
        self._connection.execute(
            update(escalations)
            .where(
                escalations.c.id == escalation_id,
                # Only an open escalation moves. Racing approvals cannot both land.
                escalations.c.status == EscalationStatus.OPEN.value,
            )
            .values(status=status.value, approval_jws=approval_jws, decided_at=decided_at)
        )

    @staticmethod
    def _to_escalation(row) -> Escalation:
        return Escalation(
            id=row["id"],
            mandate_id=row["mandate_id"],
            checkout_id=row["checkout_id"],
            merchant_id=row["merchant_id"],
            category=row["category"],
            amount=Money(row["amount_minor_units"], row["currency"], row["scale"]),
            reason_code=row["reason_code"],
            created_at=_aware(row["created_at"]),
            expires_at=_aware(row["expires_at"]),
            status=EscalationStatus(row["status"]),
            agent_id=row["agent_id"],
            approval_jws=row["approval_jws"],
            decided_at=_aware(row["decided_at"]),
        )

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select

from aval.application.services.dispute import DisputeEvidence, ReadableAuditEvent
from aval.adapters.ap2.receipts import mandate_reference
from aval.infrastructure.sqlite.models import audit_events
from aval.infrastructure.sqlite.payment_runtime_repository import SqlitePaymentRuntimeRepository


class SqliteDisputeEvidenceReader:
    """Read-only reconstruction of runtime facts for the audit/dispute boundary."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, mandate_id: str) -> DisputeEvidence | None:
        with self._engine.connect() as connection:
            capture = SqlitePaymentRuntimeRepository(connection).latest_for_mandate(mandate_id)
            if capture is None:
                return None
            rows = connection.execute(select(audit_events).where(
                audit_events.c.mandate_id == mandate_id
            ).order_by(audit_events.c.occurred_at, audit_events.c.id)).mappings().all()
        timeline = tuple(ReadableAuditEvent(
            id=row["id"], mandate_id=mandate_id, event_type=row["event_type"],
            reason_code="settled" if row["event_type"].startswith("capture.") else "revocation",
            human_summary=row["human_summary"], actor="authorization_core",
            occurred_at=row["occurred_at"].replace(tzinfo=UTC) if row["occurred_at"].tzinfo is None else row["occurred_at"],
            evidence_hash="runtime", revocation_epoch=0,
        ) for row in rows)
        checkout_mandate = f"checkout:{capture.checkout_id}"
        payment_mandate = f"payment:{capture.id}"
        committed_at = timeline[0].occurred_at if timeline else datetime.now(UTC)
        return DisputeEvidence(
            mandate_id=mandate_id, open_mandate=mandate_id, revocation_authority="runtime",
            checkout_jwt=checkout_mandate, checkout_hash=mandate_reference(checkout_mandate),
            closed_checkout_mandate=checkout_mandate, closed_payment_mandate=payment_mandate,
            merchant_authorization="runtime", authorization_proof="runtime",
            checkout_receipt=capture.checkout_receipt, payment_receipt=capture.payment_receipt,
            commit_point_at=committed_at, events=timeline,
        )

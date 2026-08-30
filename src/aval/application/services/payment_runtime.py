from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from aval.application.authorization_core import AuthorizationCore, CaptureCommand, CaptureResult
from aval.domain.money import Money
from aval.infrastructure.sqlite.vault_repository import SqliteVaultTokenRepository
from aval.infrastructure.sqlite.payment_runtime_repository import (
    PersistedRuntimeCapture, SqlitePaymentRuntimeRepository,
)
from aval.application.services.receipts import ReceiptService, SettledCaptureEvidence


@dataclass(frozen=True)
class PaymentCaptureRequest:
    mandate_id: str
    checkout_id: str
    merchant_id: str
    token: str
    amount: Money
    idempotency_key: str


class PaymentRuntime:
    """Application boundary that validates token scope before invoking the Core commit point."""

    def __init__(self, *, core: AuthorizationCore, engine: Engine, clock, receipts: ReceiptService) -> None:
        self._core = core
        self._engine = engine
        self._clock = clock
        self._receipts = receipts

    def capture(self, request: PaymentCaptureRequest) -> CaptureResult:
        with self._engine.connect() as connection:
            token = SqliteVaultTokenRepository(connection).get(request.token)
        if token is None:
            return CaptureResult(False, "vault_token_invalid")
        if not token.matches(
            mandate_id=request.mandate_id, checkout_id=request.checkout_id,
            merchant_id=request.merchant_id, amount=request.amount, now=self._clock(),
        ):
            return CaptureResult(False, "vault_token_scope_mismatch")
        result = self._core.capture(CaptureCommand(
            mandate_id=request.mandate_id, checkout_id=request.checkout_id,
            merchant_id=request.merchant_id, total=request.amount,
            idempotency_key=request.idempotency_key, instrument_id=request.token,
        ))
        if result.approved and result.reservation is not None and result.settlement_reference:
            self._persist_receipts(result)
        return result

    def _persist_receipts(self, result: CaptureResult) -> None:
        assert result.reservation is not None and result.settlement_reference is not None
        with self._engine.connect() as connection:
            if SqlitePaymentRuntimeRepository(connection).get(result.reservation.id) is not None:
                return
        checkout_receipt, payment_receipt = self._receipts.issue_after_capture(SettledCaptureEvidence(
            attempt_id=result.reservation.id, reservation=result.reservation,
            checkout_mandate=f"checkout:{result.reservation.checkout_intent_id}",
            payment_mandate=f"payment:{result.reservation.id}",
            settlement_reference=result.settlement_reference, order_id=result.reservation.checkout_intent_id,
        ))
        from aval.infrastructure.sqlite.transaction import run_in_write_transaction
        run_in_write_transaction(self._engine, lambda connection: SqlitePaymentRuntimeRepository(connection).put(
            PersistedRuntimeCapture(
                id=result.reservation.id, mandate_id=result.reservation.mandate_id,
                checkout_id=result.reservation.checkout_intent_id,
                settlement_reference=result.settlement_reference,
                checkout_receipt=checkout_receipt.payload, payment_receipt=payment_receipt.payload,
            )
        ))

    def receipts_for(self, capture_id: str) -> PersistedRuntimeCapture | None:
        with self._engine.connect() as connection:
            return SqlitePaymentRuntimeRepository(connection).get(capture_id)

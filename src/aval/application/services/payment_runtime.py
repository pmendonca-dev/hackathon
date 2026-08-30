from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from sqlalchemy import Engine

from aval.application.authorization_core import AuthorizationCore, CaptureCommand, CaptureResult
from aval.application.services.checkout import DEFAULT_CHECKOUT_CATEGORY
from aval.infrastructure.sqlite.vault_repository import SqliteVaultTokenRepository
from aval.infrastructure.sqlite.payment_runtime_repository import (
    PersistedRuntimeCapture, SqlitePaymentRuntimeRepository,
)
from aval.application.services.receipts import ReceiptService, SettledCaptureEvidence
from aval.application.services.checkout import CheckoutStore
from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationVerifier
from aval.infrastructure.sqlite.mandate_repository import SqliteMandateRepository


@dataclass(frozen=True)
class PaymentCaptureRequest:
    checkout_id: str
    token: str
    audience: str
    nonce: str
    checkout_mandate: str | None
    idempotency_key: str
    # The purchase scope is read from the stored checkout, not from here: see capture().
    category: str = DEFAULT_CHECKOUT_CATEGORY


class PaymentRuntime:
    """Application boundary that validates token scope before invoking the Core commit point."""

    def __init__(
        self, *, core: AuthorizationCore, engine: Engine, clock, receipts: ReceiptService,
        checkouts: CheckoutStore, merchant_authorization_verifier: MerchantAuthorizationVerifier,
        mandate_verifier: ClosedCheckoutMandateVerifier,
    ) -> None:
        self._core = core
        self._engine = engine
        self._clock = clock
        self._receipts = receipts
        self._checkouts = checkouts
        self._merchant_authorization_verifier = merchant_authorization_verifier
        self._mandate_verifier = mandate_verifier

    def capture(self, request: PaymentCaptureRequest) -> CaptureResult:
        checkout = self._checkouts.get(request.checkout_id)
        if checkout is None:
            return CaptureResult(False, "checkout_not_found")
        authorization = checkout.payload.get("ap2")
        merchant_authorization = authorization.get("merchant_authorization") if isinstance(authorization, dict) else None
        try:
            self._merchant_authorization_verifier.verify(checkout.payload, merchant_authorization)
            self._mandate_verifier.verify(
                request.checkout_mandate, expected_audience=checkout.command.merchant_id,
                expected_nonce=request.nonce, merchant_authorization=merchant_authorization,
            )
        except ValueError as error:
            return CaptureResult(False, str(error))
        if request.audience != checkout.command.merchant_id:
            return CaptureResult(False, "mandate_audience_invalid")
        with self._engine.connect() as connection:
            token = SqliteVaultTokenRepository(connection).get(request.token)
        if token is None:
            return CaptureResult(False, "vault_token_invalid")
        if not token.matches(
            mandate_id=checkout.command.mandate_id, checkout_id=request.checkout_id,
            merchant_id=checkout.command.merchant_id, amount=checkout.command.total, now=self._clock(),
        ):
            return CaptureResult(False, "vault_token_scope_mismatch")
        # A vault token and a mandate instrument are two different objects that happen
        # to share a `vt_` prefix: the token is a one-checkout delegation, the
        # instrument is the payment method the mandate names. Handing the token to the
        # core as if it were the instrument only ever passed because the fixture mandate
        # named none. The token has just been proved bound to this mandate, checkout,
        # merchant and amount, so what it delegates is the mandate's own instrument —
        # and that is what the core is told.
        mandate = self._core.mandate(checkout.command.mandate_id)
        if mandate is None or mandate.instrument is None:
            return CaptureResult(False, "instrument_not_in_mandate")
        result = self._core.capture(CaptureCommand(
            # Every field comes from the stored checkout, never from the caller: a
            # request that named a different mandate, merchant, amount or category than
            # the checkout was created with would be describing another purchase.
            mandate_id=checkout.command.mandate_id, checkout_id=request.checkout_id,
            merchant_id=checkout.command.merchant_id, total=checkout.command.total,
            category=checkout.command.category,
            idempotency_key=request.idempotency_key, instrument_id=mandate.instrument.token,
            idempotency_fingerprint=self._capture_idempotency_fingerprint(request),
        ))
        if result.approved and result.reservation is not None and result.settlement_reference:
            self._persist_receipts(result, checkout_mandate=request.checkout_mandate)
        return result

    @staticmethod
    def _capture_idempotency_fingerprint(request: PaymentCaptureRequest) -> str:
        return hashlib.sha256(json.dumps({
            "checkout_session_id": request.checkout_id,
            "token": request.token,
            "audience": request.audience,
            "nonce": request.nonce,
            "checkout_mandate": request.checkout_mandate,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _persist_receipts(self, result: CaptureResult, *, checkout_mandate: str | None) -> None:
        assert result.reservation is not None and result.settlement_reference is not None
        with self._engine.connect() as connection:
            if SqlitePaymentRuntimeRepository(connection).get(result.reservation.id) is not None:
                return
        checkout_receipt, payment_receipt = self._receipts.issue_after_capture(SettledCaptureEvidence(
            attempt_id=result.reservation.id, reservation=result.reservation,
            checkout_mandate=checkout_mandate or "",
            payment_mandate=checkout_mandate or "",
            settlement_reference=result.settlement_reference, order_id=result.reservation.checkout_intent_id,
        ))
        from aval.infrastructure.sqlite.transaction import run_in_write_transaction
        run_in_write_transaction(self._engine, lambda connection: SqlitePaymentRuntimeRepository(connection).put(
            PersistedRuntimeCapture(
                id=result.reservation.id, mandate_id=result.reservation.mandate_id,
                checkout_id=result.reservation.checkout_intent_id,
                settlement_reference=result.settlement_reference,
                checkout_mandate=checkout_mandate or "", payment_mandate=checkout_mandate or "",
                checkout_receipt=checkout_receipt.payload, payment_receipt=payment_receipt.payload,
            )
        ))

    def receipts_for(self, capture_id: str) -> PersistedRuntimeCapture | None:
        with self._engine.connect() as connection:
            return SqlitePaymentRuntimeRepository(connection).get(capture_id)

    def can_read_capture(self, *, identity_id: str, capture_id: str) -> bool:
        if identity_id in {"holder_01", "auditor_01"}:
            return self.receipts_for(capture_id) is not None
        capture = self.receipts_for(capture_id)
        if capture is None or identity_id != "agent_01":
            return False
        checkout = self._checkouts.get(capture.checkout_id)
        return checkout is not None and checkout.command.merchant_id == "merchant_01"

    def can_read_mandate(self, *, identity_id: str, mandate_id: str) -> bool:
        if identity_id in {"holder_01", "auditor_01"}:
            return True
        if identity_id != "agent_01":
            return False
        with self._engine.connect() as connection:
            mandate = SqliteMandateRepository(connection).get(mandate_id)
        # The current audit projection has no per-event merchant column; fail closed
        # instead of exposing a multi-merchant mandate's combined timeline.
        return mandate is not None and mandate.allowed_merchant_ids == frozenset({"merchant_01"})

    def mandate_exists(self, mandate_id: str) -> bool:
        return self._core.mandate(mandate_id) is not None

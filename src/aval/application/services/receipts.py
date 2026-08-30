from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol
from uuid import uuid4

from aval.domain.entities import Evidence, Reservation
from aval.domain.enums import ReservationStatus


@dataclass(frozen=True)
class SettledCaptureEvidence:
    attempt_id: str
    reservation: Reservation
    checkout_mandate: str
    payment_mandate: str
    settlement_reference: str
    order_id: str


class CheckoutReceiptIssuer(Protocol):
    def issue_checkout(self, *, closed_mandate: str, order_id: str) -> str: ...


class PaymentReceiptIssuer(Protocol):
    def issue_payment(
        self,
        *,
        closed_mandate: str,
        payment_id: str,
        psp_confirmation_id: str,
    ) -> str: ...


class ReceiptService:
    """Returns immutable receipt evidence for the core to persist and audit."""

    def __init__(
        self,
        *,
        checkout_issuer: CheckoutReceiptIssuer,
        payment_issuer: PaymentReceiptIssuer,
    ) -> None:
        self._checkout_issuer = checkout_issuer
        self._payment_issuer = payment_issuer

    def issue_after_capture(
        self, capture: SettledCaptureEvidence
    ) -> tuple[Evidence, Evidence]:
        if capture.reservation.status is not ReservationStatus.SETTLED:
            raise ValueError("receipts require a settled capture")

        checkout_token = self._checkout_issuer.issue_checkout(
            closed_mandate=capture.checkout_mandate,
            order_id=capture.order_id,
        )
        payment_token = self._payment_issuer.issue_payment(
            closed_mandate=capture.payment_mandate,
            payment_id=capture.attempt_id,
            psp_confirmation_id=capture.settlement_reference,
        )
        return (
            self._evidence("ap2.checkout_receipt.v0.2", "merchant", checkout_token),
            self._evidence("ap2.payment_receipt.v0.2", "psp", payment_token),
        )

    @staticmethod
    def _evidence(kind: str, origin: str, payload: str) -> Evidence:
        return Evidence(
            id=f"ev_{uuid4().hex}",
            kind=kind,
            origin=origin,
            sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            payload=payload,
        )

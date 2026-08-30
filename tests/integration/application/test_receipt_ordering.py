from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aval.adapters.ap2.receipts import Ap2ReceiptIssuer, mandate_reference
from aval.application.services.receipts import ReceiptService, SettledCaptureEvidence
from aval.domain.entities import Reservation
from aval.domain.money import Money
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def test_receipts_are_signed_and_issued_only_after_settlement() -> None:
    now = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("merchant-receipts")
    custody.generate_es256("psp-receipts")
    service = ReceiptService(
        checkout_issuer=Ap2ReceiptIssuer(
            issuer="merchant_aval",
            custody=custody,
            kid="merchant-receipts",
            clock=lambda: now,
        ),
        payment_issuer=Ap2ReceiptIssuer(
            issuer="psp_mock",
            custody=custody,
            kid="psp-receipts",
            clock=lambda: now,
        ),
    )
    committed = Reservation(
        "rsv_1", "mandate_1", "checkout_1", Money(5_000, "BRL", 2)
    ).commit("transaction_hash")
    capture = SettledCaptureEvidence(
        attempt_id="cap_1",
        reservation=committed,
        checkout_mandate="closed-checkout-mandate",
        payment_mandate="closed-payment-mandate",
        settlement_reference="psp_mock_123",
        order_id="order_1",
    )

    with pytest.raises(ValueError, match="settled"):
        service.issue_after_capture(capture)

    checkout_receipt, payment_receipt = service.issue_after_capture(
        SettledCaptureEvidence(**{**capture.__dict__, "reservation": committed.settle()})
    )
    checkout_payload = verify_compact_jws(
        checkout_receipt.payload,
        public_key_from_jwk(custody.public_jwk("merchant-receipts")),
    )
    payment_payload = verify_compact_jws(
        payment_receipt.payload,
        public_key_from_jwk(custody.public_jwk("psp-receipts")),
    )

    assert [checkout_receipt.kind, payment_receipt.kind] == [
        "ap2.checkout_receipt.v0.2",
        "ap2.payment_receipt.v0.2",
    ]
    assert checkout_payload == {
        "status": "Success",
        "iss": "merchant_aval",
        "iat": int(now.timestamp()),
        "reference": mandate_reference("closed-checkout-mandate"),
        "order_id": "order_1",
    }
    assert payment_payload == {
        "status": "Success",
        "iss": "psp_mock",
        "iat": int(now.timestamp()),
        "reference": mandate_reference("closed-payment-mandate"),
        "payment_id": "cap_1",
        "psp_confirmation_id": "psp_mock_123",
    }

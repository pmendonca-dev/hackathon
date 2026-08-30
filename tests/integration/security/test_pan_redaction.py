from __future__ import annotations

from datetime import UTC, datetime
import json

from aval.adapters.acp.delegate_payment import (
    OpaqueTestCredentialTokenizer,
    serialize_delegated_payment,
)
from aval.application.services.vault import ApprovedPaymentContext, VaultService
from aval.domain.money import Money


class MockApprovedAuthorizer:
    def authorize_delegation(self, *, mandate_id: str, checkout_id: str, merchant_id: str):
        return ApprovedPaymentContext(
            live_balance=Money(5_000, "BRL", 2),
            mandate_ceiling=Money(5_000, "BRL", 2),
            checkout_total=Money(5_000, "BRL", 2),
            merchant_id=merchant_id,
            checkout_id=checkout_id,
            expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_pan_is_neither_returned_nor_retained_by_the_mock_tokenizer() -> None:
    pan = "4242424242424242"
    tokenizer = OpaqueTestCredentialTokenizer()
    delegated = VaultService(authorizer=MockApprovedAuthorizer(), tokenizer=tokenizer).delegate(
        mandate_id="mandate_1",
        checkout_id="checkout_42",
        merchant_id="merchant_aval",
        card_number=pan,
    )

    wire_payload = json.dumps(serialize_delegated_payment(delegated), sort_keys=True)

    assert pan not in wire_payload
    assert pan not in repr(vars(tokenizer))
    assert delegated.token.startswith("vt_")

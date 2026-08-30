from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import HTTPException
import pytest

from aval.adapters.acp.delegate_payment import OpaqueTestCredentialTokenizer
from aval.api.routers.delegate_payment import (
    CardCredentialInput,
    DelegatePaymentRequest,
    create_delegate_payment_router,
)
from aval.application.services.vault import (
    ApprovedPaymentContext,
    DelegationRejected,
    VaultService,
)
from aval.domain.money import Money


class MockLiveAuthorizer:
    """Temporary Laptop-A contract fixture; it returns server-owned live facts."""

    def __init__(self) -> None:
        self.live_limit = 8_000

    def authorize_delegation(self, *, mandate_id: str, checkout_id: str, merchant_id: str):
        return ApprovedPaymentContext(
            live_balance=Money(self.live_limit, "BRL", 2),
            mandate_ceiling=Money(12_000, "BRL", 2),
            checkout_total=Money(9_500, "BRL", 2),
            merchant_id=merchant_id,
            checkout_id=checkout_id,
            expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_delegate_payment_uses_fresh_authorized_state_for_each_token() -> None:
    authorizer = MockLiveAuthorizer()
    service = VaultService(authorizer=authorizer, tokenizer=OpaqueTestCredentialTokenizer())
    router = create_delegate_payment_router(service)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/agentic_commerce/delegate_payment")
    request = DelegatePaymentRequest(
        mandate_id="mandate_1",
        checkout_session_id="checkout_42",
        merchant_id="merchant_aval",
        payment_method=CardCredentialInput(card_number="4242424242424242"),
    )

    first = asyncio.run(endpoint(request, "idem-1"))
    authorizer.live_limit = 4_000
    second = asyncio.run(endpoint(request, "idem-2"))

    assert first.token.startswith("vt_")
    assert second.token.startswith("vt_")
    assert first.token != second.token
    assert first.allowance.max_amount == 8_000
    assert second.allowance.max_amount == 4_000
    assert second.allowance.currency == "brl"


def test_revoked_mandate_is_rejected_before_the_card_is_tokenized() -> None:
    class MockRevokedAuthorizer:
        def authorize_delegation(self, *, mandate_id: str, checkout_id: str, merchant_id: str):
            raise DelegationRejected("mandate_revoked")

    class SpyTokenizer:
        called = False

        def tokenize(self, card_number: str) -> str:
            self.called = True
            return "vt_should_not_exist"

    tokenizer = SpyTokenizer()
    service = VaultService(authorizer=MockRevokedAuthorizer(), tokenizer=tokenizer)
    router = create_delegate_payment_router(service)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/agentic_commerce/delegate_payment")
    request = DelegatePaymentRequest(
        mandate_id="mandate_1",
        checkout_session_id="checkout_42",
        merchant_id="merchant_aval",
        payment_method=CardCredentialInput(card_number="4242424242424242"),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(endpoint(request, "idem-revoked"))

    assert tokenizer.called is False
    assert raised.value.status_code == 403
    assert raised.value.detail == "mandate_revoked"

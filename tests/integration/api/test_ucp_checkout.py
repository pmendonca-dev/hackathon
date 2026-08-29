from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationSigner
from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY, UcpCheckoutError
from aval.application.authorization_core import AuthorizationResult, CaptureResult
from aval.application.services.checkout import CheckoutCommand, CheckoutService, InMemoryCheckoutStore
from aval.domain.enums import AuthorizationDecision
from aval.domain.money import Money
from aval.security.key_custody import KeyCustodyService


class AuthorizingCore:
    def evaluate(self, command):
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada.")


class CapturingCore(AuthorizingCore):
    def __init__(self) -> None:
        self.idempotency_keys: list[str] = []

    def capture(self, command):
        self.idempotency_keys.append(command.idempotency_key)
        return CaptureResult(True, "committed")


def test_ap2_checkout_is_security_locked_and_returns_merchant_authorization() -> None:
    """Catches a UCP checkout that negotiates AP2 but returns an unsigned mutable response."""
    custody = KeyCustodyService()
    custody.generate_es256("merchant-key")
    service = CheckoutService(
        core=AuthorizingCore(),
        store=InMemoryCheckoutStore(),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )

    checkout = service.create(
        CheckoutCommand(
            id="chi_1",
            mandate_id="mandate_1",
            merchant_id="merchant_1",
            total=Money(500, "BRL", 2),
            line_items=({"id": "coffee", "quantity": 1, "amount": 500},),
            negotiated_capabilities=frozenset({AP2_MANDATE_CAPABILITY}),
        )
    )

    assert checkout.payload["status"] == "ready_for_complete"
    assert checkout.payload["ap2"]["merchant_authorization"].count(".") == 2
    with pytest.raises(UcpCheckoutError, match="mandate_required"):
        service.complete("chi_1", checkout_mandate=None, audience="merchant.example", nonce="nonce-1", idempotency_key="i1")


def test_complete_checkout_delegates_stateful_capture_to_the_core() -> None:
    """Catches an adapter-only completion that succeeds without invoking the AVAL commit path."""
    custody = KeyCustodyService()
    custody.generate_es256("merchant-key")
    core = CapturingCore()
    service = CheckoutService(
        core=core,
        store=InMemoryCheckoutStore(),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    service.create(
        CheckoutCommand("chi_2", "mandate_1", "merchant_1", Money(500, "BRL", 2), ({"id": "coffee", "quantity": 1, "amount": 500},), frozenset())
    )

    result = service.complete("chi_2", checkout_mandate=None, audience="merchant_1", nonce="unused", idempotency_key="i2")

    assert result == CaptureResult(True, "committed")
    assert core.idempotency_keys == ["i2"]

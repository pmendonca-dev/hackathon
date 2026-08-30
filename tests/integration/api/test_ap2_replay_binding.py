from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from aval.adapters.ap2.mandates import Ap2MandateError, ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationSigner, MerchantAuthorizationVerifier
from aval.adapters.ucp.ap2_extension import AP2_MANDATE_CAPABILITY
from aval.application.authorization_core import AuthorizationResult
from aval.application.services.checkout import CheckoutCommand, CheckoutService, InMemoryCheckoutStore
from aval.domain.enums import AuthorizationDecision
from aval.domain.money import Money
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def _sha256_b64url(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class AuthorizingCore:
    def evaluate(self, command):
        return AuthorizationResult(AuthorizationDecision.AUTHORIZED, "authorized", "Compra autorizada.")


def test_complete_checkout_rejects_a_closed_mandate_with_a_replayed_nonce() -> None:
    """Catches completion that accepts a valid AP2 proof bound to a different merchant challenge."""
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    for kid in ("merchant-key", "issuer-key", "holder-key"):
        custody.generate_es256(kid)
    service = CheckoutService(
        core=AuthorizingCore(),
        store=InMemoryCheckoutStore(),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(custody.public_jwk("merchant-key")),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"), holder_jwk=custody.public_jwk("holder-key"), clock=lambda: now
        ),
        clock=lambda: now,
    )
    checkout = service.create(
        CheckoutCommand("chi_1", "mandate_1", "merchant_1", Money(500, "BRL", 2), ({"id": "coffee", "quantity": 1, "amount": 500},), frozenset({AP2_MANDATE_CAPABILITY}))
    )
    merchant_authorization = checkout.payload["ap2"]["merchant_authorization"]
    issuer_jwt = sign_compact_jws(
        {"vct": "mandate.checkout.1", "exp": int((now + timedelta(minutes=5)).timestamp()), "checkout_hash": _sha256_b64url(merchant_authorization)},
        custody, "issuer-key",
    )
    kb_jwt = sign_compact_jws(
        {"aud": "merchant_1", "nonce": "old-nonce", "sd_hash": _sha256_b64url(issuer_jwt)}, custody, "holder-key"
    )

    with pytest.raises(Ap2MandateError, match="mandate_nonce_invalid"):
        service.complete("chi_1", checkout_mandate=f"{issuer_jwt}~{kb_jwt}", audience="merchant_1", nonce="new-nonce", idempotency_key="i1")

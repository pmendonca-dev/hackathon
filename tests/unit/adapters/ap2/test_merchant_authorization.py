from __future__ import annotations

import pytest

from aval.adapters.ap2.merchant_authorization import (
    MerchantAuthorizationError,
    MerchantAuthorizationSigner,
    MerchantAuthorizationVerifier,
)
from aval.security.key_custody import KeyCustodyService


def test_detached_merchant_authorization_binds_the_complete_checkout_except_ap2() -> None:
    """Catches a merchant proof that accepts a changed total or strips an unknown signed field."""
    custody = KeyCustodyService()
    custody.generate_es256("merchant-key")
    checkout = {
        "id": "chi_1",
        "merchant_id": "merchant_1",
        "line_items": [{"id": "coffee", "name": "Café ☕", "quantity": 1, "amount": 500}],
        "total": {"minor_units": 500, "currency": "BRL", "scale": 2},
        "extension": {"z": 1, "á": "preservado"},
        "ap2": {"must_not_be_signed": True},
    }
    proof = MerchantAuthorizationSigner(custody=custody, key_id="merchant-key").sign(checkout)
    verifier = MerchantAuthorizationVerifier(custody.public_jwk("merchant-key"))

    verifier.verify(checkout, proof)

    tampered = {**checkout, "total": {"minor_units": 501, "currency": "BRL", "scale": 2}}
    with pytest.raises(MerchantAuthorizationError, match="merchant_authorization_invalid"):
        verifier.verify(tampered, proof)

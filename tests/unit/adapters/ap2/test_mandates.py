from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from aval.adapters.ap2.mandates import Ap2MandateError, ClosedCheckoutMandateVerifier
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def _b64url_sha256(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def test_closed_checkout_mandate_rejects_an_incorrect_key_binding_audience() -> None:
    """Catches a replayable AP2 mandate whose KB-JWT audience is ignored."""
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("issuer-key")
    custody.generate_es256("holder-key")
    merchant_authorization = "merchant-header..merchant-signature"
    issuer_jwt = sign_compact_jws(
        {
            "vct": "mandate.checkout.1",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "checkout_hash": _b64url_sha256(merchant_authorization),
        },
        custody,
        "issuer-key",
    )
    kb_jwt = sign_compact_jws(
        {"aud": "wrong-merchant.example", "nonce": "nonce-1", "sd_hash": _b64url_sha256(issuer_jwt)},
        custody,
        "holder-key",
    )

    verifier = ClosedCheckoutMandateVerifier(
        issuer_jwk=custody.public_jwk("issuer-key"), holder_jwk=custody.public_jwk("holder-key"), clock=lambda: now
    )

    with pytest.raises(Ap2MandateError, match="mandate_audience_invalid"):
        verifier.verify(
            f"{issuer_jwt}~{kb_jwt}",
            expected_audience="merchant.example",
            expected_nonce="nonce-1",
            merchant_authorization=merchant_authorization,
        )


def test_closed_checkout_mandate_rejects_expired_evidence() -> None:
    """Catches an AP2 verifier that accepts an otherwise-valid closed mandate after exp."""
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("issuer-key")
    custody.generate_es256("holder-key")
    merchant_authorization = "merchant-header..merchant-signature"
    issuer_jwt = sign_compact_jws(
        {"vct": "mandate.checkout.1", "exp": int((now - timedelta(seconds=1)).timestamp()), "checkout_hash": _b64url_sha256(merchant_authorization)},
        custody, "issuer-key",
    )
    kb_jwt = sign_compact_jws(
        {"aud": "merchant.example", "nonce": "nonce-1", "sd_hash": _b64url_sha256(issuer_jwt)}, custody, "holder-key"
    )
    verifier = ClosedCheckoutMandateVerifier(
        issuer_jwk=custody.public_jwk("issuer-key"), holder_jwk=custody.public_jwk("holder-key"), clock=lambda: now
    )

    with pytest.raises(Ap2MandateError, match="mandate_expired"):
        verifier.verify(
            f"{issuer_jwt}~{kb_jwt}",
            expected_audience="merchant.example",
            expected_nonce="nonce-1",
            merchant_authorization=merchant_authorization,
        )

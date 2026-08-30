from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from aval.security.jws import verify_compact_jws
from aval.security.key_custody import public_key_from_jwk


class Ap2MandateError(ValueError):
    pass


def _b64url_sha256(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class VerifiedClosedCheckoutMandate:
    checkout_hash: str
    expires_at: datetime


class ClosedCheckoutMandateVerifier:
    """Verifies the AP2 v0.2 closed-checkout evidence required at UCP completion."""

    def __init__(
        self,
        *,
        issuer_jwk: Mapping[str, str],
        holder_jwk: Mapping[str, str],
        clock: Callable[[], datetime],
    ) -> None:
        self._issuer_key = public_key_from_jwk(dict(issuer_jwk))
        self._holder_key = public_key_from_jwk(dict(holder_jwk))
        self._clock = clock

    def verify(
        self,
        evidence: str | None,
        *,
        expected_audience: str,
        expected_nonce: str,
        merchant_authorization: str,
    ) -> VerifiedClosedCheckoutMandate:
        if not evidence:
            raise Ap2MandateError("mandate_required")
        parts = evidence.split("~")
        if len(parts) != 2 or not all(parts):
            raise Ap2MandateError("mandate_invalid_signature")
        issuer_jwt, kb_jwt = parts
        try:
            issuer_claims = verify_compact_jws(issuer_jwt, self._issuer_key)
            kb_claims = verify_compact_jws(kb_jwt, self._holder_key)
        except ValueError as error:
            raise Ap2MandateError("mandate_invalid_signature") from error
        if issuer_claims.get("vct") != "mandate.checkout.1":
            raise Ap2MandateError("mandate_scope_mismatch")
        expires = issuer_claims.get("exp")
        if not isinstance(expires, int):
            raise Ap2MandateError("mandate_invalid_signature")
        expires_at = datetime.fromtimestamp(expires, tz=self._clock().tzinfo)
        if self._clock() >= expires_at:
            raise Ap2MandateError("mandate_expired")
        if issuer_claims.get("checkout_hash") != _b64url_sha256(merchant_authorization):
            raise Ap2MandateError("mandate_scope_mismatch")
        if kb_claims.get("aud") != expected_audience:
            raise Ap2MandateError("mandate_audience_invalid")
        if kb_claims.get("nonce") != expected_nonce:
            raise Ap2MandateError("mandate_nonce_invalid")
        if kb_claims.get("sd_hash") != _b64url_sha256(issuer_jwt):
            raise Ap2MandateError("mandate_invalid_signature")
        return VerifiedClosedCheckoutMandate(issuer_claims["checkout_hash"], expires_at)

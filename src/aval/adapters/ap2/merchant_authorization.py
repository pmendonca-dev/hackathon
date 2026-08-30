from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from aval.security.ecdsa import verify_es256_raw
from aval.security.jcs import canonicalize
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


class MerchantAuthorizationError(ValueError):
    pass


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_checkout(checkout: Mapping[str, Any]) -> bytes:
    """Return the complete JCS checkout representation excluding only the AP2 wrapper."""
    return canonicalize({key: value for key, value in checkout.items() if key != "ap2"})


class MerchantAuthorizationSigner:
    def __init__(self, *, custody: KeyCustodyService, key_id: str) -> None:
        self._custody = custody
        self._key_id = key_id

    def sign(self, checkout: Mapping[str, Any]) -> str:
        header = _b64url(json.dumps({"alg": "ES256", "kid": self._key_id}, separators=(",", ":")).encode())
        payload = _b64url(canonical_checkout(checkout))
        signature = _b64url(self._custody.sign_es256(self._key_id, f"{header}.{payload}".encode("ascii")))
        return f"{header}..{signature}"


class MerchantAuthorizationVerifier:
    def __init__(self, public_jwk: Mapping[str, str]) -> None:
        self._public_jwk = dict(public_jwk)

    def verify(self, checkout: Mapping[str, Any], proof: str | None) -> None:
        if not proof:
            raise MerchantAuthorizationError("merchant_authorization_missing")
        try:
            encoded_header, detached_payload, encoded_signature = proof.split(".")
            header = json.loads(_b64url_decode(encoded_header))
            signature = _b64url_decode(encoded_signature)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MerchantAuthorizationError("merchant_authorization_invalid") from error
        if detached_payload or header.get("alg") != "ES256" or header.get("kid") != self._public_jwk.get("kid"):
            raise MerchantAuthorizationError("merchant_authorization_invalid")
        payload = _b64url(canonical_checkout(checkout))
        try:
            valid = verify_es256_raw(
                public_key_from_jwk(self._public_jwk), f"{encoded_header}.{payload}".encode("ascii"), signature
            )
        except ValueError as error:
            raise MerchantAuthorizationError("merchant_authorization_invalid") from error
        if not valid:
            raise MerchantAuthorizationError("merchant_authorization_invalid")

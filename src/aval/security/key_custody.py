from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class KeyCustodyService:
    """In-memory demo custody; keys never cross the service boundary."""

    def __init__(self) -> None:
        self._keys: dict[str, ec.EllipticCurvePrivateKey] = {}

    def generate_es256(self, kid: str) -> None:
        if not kid or kid in self._keys:
            raise ValueError("kid must be new and non-empty")
        self._keys[kid] = ec.generate_private_key(ec.SECP256R1())

    def private_key(self, kid: str) -> ec.EllipticCurvePrivateKey:
        return self._keys[kid]

    def public_key(self, kid: str) -> ec.EllipticCurvePublicKey:
        return self.private_key(kid).public_key()

    def public_jwk(self, kid: str) -> dict[str, str]:
        numbers = self.public_key(kid).public_numbers()
        return {
            "kid": kid,
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(numbers.x.to_bytes(32, "big")),
            "y": _b64url(numbers.y.to_bytes(32, "big")),
            "alg": "ES256",
        }

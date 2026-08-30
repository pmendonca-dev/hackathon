from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric import ec

from aval.security.ecdsa import sign_es256_raw


P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def public_key_from_jwk(jwk: dict[str, str] | object) -> ec.EllipticCurvePublicKey:
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("only P-256 EC JWKs are supported")
    try:
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_b64url_decode(jwk["x"]), "big"),
            int.from_bytes(_b64url_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        )
        return numbers.public_key()
    except (KeyError, ValueError) as error:
        raise ValueError("invalid P-256 JWK") from error


def _private_value_from(material: bytes) -> int:
    """A valid P-256 scalar from 32 bytes of key material.

    The reduction leaves a bias, and at this order it is far below anything that
    matters: `n` is within 2**-128 of 2**256, so the first values are reachable by one
    extra path out of 2**128. Uniform sampling would need rejection, and rejection would
    make derivation non-total — the wrong trade for a key that must be reproducible.
    """
    return (int.from_bytes(material, "big") % (P256_ORDER - 1)) + 1


class KeyCustodyService:
    """In-memory demo custody; keys never cross the service boundary.

    Keys arrive one of two ways. `generate_es256` draws a fresh one, which is right for
    a throwaway instance and wrong for a deployment: it dies with the process, while the
    database goes on holding the public half that was registered under it. `derive_es256`
    reproduces the same key from a seed the operator keeps, so a restart — or a second
    process — finds the key the database already trusts.
    """

    def __init__(self) -> None:
        self._keys: dict[str, ec.EllipticCurvePrivateKey] = {}

    def generate_es256(self, kid: str) -> None:
        if not kid or kid in self._keys:
            raise ValueError("kid must be new and non-empty")
        self._keys[kid] = ec.generate_private_key(ec.SECP256R1())

    def derive_es256(self, kid: str, *, secret: str, domain: str) -> None:
        """Reproduce one key from one seed, separated by domain and kid.

        `domain` is what keeps the several custodies in this system apart. The agent
        holds its own custody and the protocol lane holds another; both name keys, and
        one seed feeding both must not let an agent sign as the protocol lane. Without
        the kid in the message every role would share a single key, and the merchant
        could sign what only the processor may sign.
        """
        if not kid or kid in self._keys:
            raise ValueError("kid must be new and non-empty")
        if not secret or not domain:
            raise ValueError("secret and domain must be non-empty")
        material = hmac.new(
            b"AVAL custody ES256 v1",
            f"{domain}|{kid}|{secret}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        self._keys[kid] = ec.derive_private_key(_private_value_from(material), ec.SECP256R1())

    def derive_es256_from_secret(self, kid: str, secret: str) -> None:
        """Install an explicit server-only deterministic demo authority key."""
        if not kid or kid in self._keys or not secret:
            raise ValueError("kid and secret must be new and non-empty")
        material = hmac.new(
            b"AVAL operator authority ES256 v1",
            secret.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        self._keys[kid] = ec.derive_private_key(_private_value_from(material), ec.SECP256R1())

    def has(self, kid: str) -> bool:
        return kid in self._keys

    def verifying_key(self, kid: str) -> ec.EllipticCurvePublicKey:
        """The public half, rebuilt from the JWK this service publishes.

        Going through the JWK on purpose: it is the same material an outside verifier
        would fetch, so nothing here can verify with a key the world cannot see — and the
        private key still never crosses the boundary.
        """
        return public_key_from_jwk(self.public_jwk(kid))

    def sign_es256(self, kid: str, payload: bytes) -> bytes:
        try:
            private_key = self._keys[kid]
        except KeyError as error:
            raise ValueError("unknown custody key") from error
        return sign_es256_raw(private_key, payload)

    def public_jwk(self, kid: str) -> dict[str, str]:
        try:
            numbers = self._keys[kid].public_key().public_numbers()
        except KeyError as error:
            raise ValueError("unknown custody key") from error
        return {
            "kid": kid,
            "kty": "EC",
            "crv": "P-256",
            "x": _b64url(numbers.x.to_bytes(32, "big")),
            "y": _b64url(numbers.y.to_bytes(32, "big")),
            "alg": "ES256",
        }

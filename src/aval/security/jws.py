from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec

from aval.security.ecdsa import sign_es256_raw, verify_es256_raw
from aval.security.key_custody import KeyCustodyService


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_compact_jws(payload: dict[str, Any], custody: KeyCustodyService, kid: str) -> str:
    header = _b64url_encode(json.dumps({"alg": "ES256", "kid": kid}, separators=(",", ":")).encode())
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{header}.{encoded_payload}".encode("ascii")
    signature = _b64url_encode(sign_es256_raw(custody.private_key(kid), signing_input))
    return f"{header}.{encoded_payload}.{signature}"


def verify_compact_jws(token: str, public_key: ec.EllipticCurvePublicKey) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
        signature = _b64url_decode(encoded_signature)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("malformed compact JWS") from error
    if header.get("alg") != "ES256" or not isinstance(payload, dict):
        raise ValueError("unsupported compact JWS")
    if not verify_es256_raw(public_key, f"{encoded_header}.{encoded_payload}".encode("ascii"), signature):
        raise ValueError("invalid compact JWS signature")
    return payload

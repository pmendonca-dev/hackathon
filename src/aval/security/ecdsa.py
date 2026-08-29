from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)


def sign_es256_raw(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> bytes:
    der_signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify_es256_raw(
    public_key: ec.EllipticCurvePublicKey, message: bytes, signature: bytes
) -> bool:
    if len(signature) != 64:
        raise ValueError("ES256 signatures must be 64-byte R||S values")
    der_signature = encode_dss_signature(
        int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    )
    try:
        public_key.verify(der_signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True

from __future__ import annotations

import base64

import pytest

from aval.security.content_digest import content_digest_sha256, verify_content_digest_sha256
from aval.security.ecdsa import verify_es256_raw
from aval.security.jcs import canonicalize
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def test_content_digest_covers_exact_raw_utf8_bytes():
    raw = b'{"message":"ol\xc3\xa1"}'
    digest = content_digest_sha256(raw)

    assert digest.startswith("sha-256=:")
    assert verify_content_digest_sha256(raw, digest)
    assert not verify_content_digest_sha256(b'{"message":"ola"}', digest)


def test_jcs_produces_deterministic_utf8_bytes():
    assert canonicalize({"z": 1, "a": "olá"}) == b'{"a":"ol\xc3\xa1","z":1}'


def test_es256_boundary_uses_fixed_length_raw_r_and_s():
    custody = KeyCustodyService()
    custody.generate_es256("test-key")
    message = b"authorization-proof"

    signature = custody.sign_es256("test-key", message)
    public_key = public_key_from_jwk(custody.public_jwk("test-key"))

    assert len(signature) == 64
    assert verify_es256_raw(public_key, message, signature)
    assert not verify_es256_raw(public_key, b"tampered", signature)

    with pytest.raises(ValueError):
        verify_es256_raw(public_key, message, signature[:-1])

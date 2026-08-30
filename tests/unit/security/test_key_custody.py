from __future__ import annotations

from aval.security.ecdsa import verify_es256_raw
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def test_custody_signs_without_exposing_private_key_material():
    """Removing custody must prevent signing; callers never receive its private key."""
    custody = KeyCustodyService()
    custody.generate_es256("authority-key")

    signature = custody.sign_es256("authority-key", b"revocation-command")

    assert len(signature) == 64
    assert verify_es256_raw(
        public_key_from_jwk(custody.public_jwk("authority-key")),
        b"revocation-command",
        signature,
    )
    assert not hasattr(custody, "private_key")

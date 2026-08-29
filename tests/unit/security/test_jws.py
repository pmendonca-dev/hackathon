from __future__ import annotations

import pytest

from aval.security.jws import sign_compact_jws, verify_compact_jws
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def test_jws_uses_es256_and_rejects_tampered_payload():
    custody = KeyCustodyService()
    custody.generate_es256("issuer-key")

    token = sign_compact_jws({"mandate_id": "m_1"}, custody, "issuer-key")

    public_key = public_key_from_jwk(custody.public_jwk("issuer-key"))
    assert verify_compact_jws(token, public_key) == {"mandate_id": "m_1"}

    header, payload, signature = token.split(".")
    with pytest.raises(ValueError):
        verify_compact_jws(f"{header}.{payload[:-1]}A.{signature}", public_key)

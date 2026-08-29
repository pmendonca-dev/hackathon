from __future__ import annotations

import pytest

from aval.security.jws import sign_compact_jws, verify_compact_jws
from aval.security.key_custody import KeyCustodyService


def test_jws_uses_es256_and_rejects_tampered_payload():
    custody = KeyCustodyService()
    custody.generate_es256("issuer-key")

    token = sign_compact_jws({"mandate_id": "m_1"}, custody, "issuer-key")

    assert verify_compact_jws(token, custody.public_key("issuer-key")) == {"mandate_id": "m_1"}

    header, payload, signature = token.split(".")
    with pytest.raises(ValueError):
        verify_compact_jws(f"{header}.{payload[:-1]}A.{signature}", custody.public_key("issuer-key"))

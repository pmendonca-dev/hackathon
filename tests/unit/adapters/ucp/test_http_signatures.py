from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from aval.adapters.ucp.http_signatures import (
    Rfc9421Verifier,
    SignedRequest,
    UcpAuthenticationError,
    signature_base,
)
from aval.domain.entities import AgentIdentity
from aval.security.key_custody import KeyCustodyService


class TrustedRegistry:
    def __init__(self, identity: AgentIdentity) -> None:
        self._identity = identity

    def resolve(self, profile_url: str) -> AgentIdentity | None:
        return self._identity if profile_url == self._identity.profile_url else None


def test_rejects_a_der_signature_even_when_its_ecdsa_math_is_valid() -> None:
    """Catches an RFC 9421 boundary that accepts library-native DER bytes."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    identity = AgentIdentity(
        id="agent_1",
        profile_url="https://agent.example/.well-known/ucp",
        public_jwk=custody.public_jwk("agent-key"),
        trusted=True,
    )
    request = SignedRequest(
        method="POST",
        authority="merchant.example",
        path="/checkout-sessions",
        headers={
            "ucp-agent": 'profile="https://agent.example/.well-known/ucp"',
            "idempotency-key": "idem-1",
            "content-digest": "sha-256=:placeholder:",
            "content-type": "application/json",
            "signature-input": (
                'sig1=("@method" "@authority" "@path" "ucp-agent" '
                '"idempotency-key" "content-digest" "content-type");keyid="agent-key";alg="es256"'
            ),
        },
        body=b'{"item":"Caf\xc3\xa9"}',
    )
    request = request.with_content_digest()
    private_key = custody._keys["agent-key"]
    der_signature = private_key.sign(signature_base(request), ec.ECDSA(hashes.SHA256()))
    request = request.with_header(
        "signature", f"sig1=:{base64.b64encode(der_signature).decode('ascii')}:"
    )

    with pytest.raises(UcpAuthenticationError, match="signature_invalid"):
        Rfc9421Verifier(TrustedRegistry(identity)).verify(request)

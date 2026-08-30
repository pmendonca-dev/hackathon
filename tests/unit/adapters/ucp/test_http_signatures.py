from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime

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
from aval.security.http_signature import ReplayGuard
from aval.security.key_custody import KeyCustodyService

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _verifier(identity: AgentIdentity) -> Rfc9421Verifier:
    """A verifier wired the way the runtime wires one: a clock and a nonce memory."""
    return Rfc9421Verifier(TrustedRegistry(identity), clock=lambda: NOW, seen=ReplayGuard())


class TrustedRegistry:
    def __init__(self, identity: AgentIdentity) -> None:
        self._identity = identity

    def resolve(self, profile_url: str) -> AgentIdentity | None:
        return self._identity if profile_url == self._identity.profile_url else None


def _valid_request(custody: KeyCustodyService, *, key_id: str = "agent-key") -> SignedRequest:
    request = SignedRequest(
        method="POST",
        authority="merchant.example",
        path="/checkout-sessions",
        headers={
            "ucp-agent": 'profile="https://agent.example/.well-known/ucp"',
            "idempotency-key": "idem-1",
            "content-type": "application/json",
            "signature-input": (
                'sig1=("@method" "@authority" "@path" "ucp-agent" '
                f'"idempotency-key" "content-digest" "content-type");keyid="{key_id}";alg="es256"'
                f';created={int(NOW.timestamp())};nonce="{secrets.token_hex(8)}"'
            ),
        },
        body=b'{"z":"Caf\xc3\xa9","a":1}',
    ).with_content_digest()
    return request.with_header(
        "signature", f"sig1=:{base64.b64encode(custody.sign_es256(key_id, signature_base(request))).decode('ascii')}:"
    )


def _identity(custody: KeyCustodyService) -> AgentIdentity:
    return AgentIdentity(
        id="agent_1",
        profile_url="https://agent.example/.well-known/ucp",
        public_jwk=custody.public_jwk("agent-key"),
        trusted=True,
    )


def test_rejects_a_der_signature_even_when_its_ecdsa_math_is_valid() -> None:
    """Catches an RFC 9421 boundary that accepts library-native DER bytes."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    identity = _identity(custody)
    request = _valid_request(custody)
    private_key = custody._keys["agent-key"]
    der_signature = private_key.sign(signature_base(request), ec.ECDSA(hashes.SHA256()))
    request = request.with_header(
        "signature", f"sig1=:{base64.b64encode(der_signature).decode('ascii')}:"
    )

    with pytest.raises(UcpAuthenticationError, match="signature_invalid"):
        _verifier(identity).verify(request)


def test_rejects_an_unsigned_request_before_it_can_reach_checkout() -> None:
    """Catches a route that trusts the UCP-Agent header without RFC 9421 proof."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    request = _valid_request(custody).with_header("signature", "")

    with pytest.raises(UcpAuthenticationError, match="signature_missing"):
        _verifier(_identity(custody)).verify(request)


def test_rejects_a_profile_absent_from_the_local_trust_registry() -> None:
    """Catches an SSRF-style fallback to an arbitrary request-supplied profile URL."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    request = _valid_request(custody).with_header(
        "ucp-agent", 'profile="https://impostor.example/.well-known/ucp"'
    )

    with pytest.raises(UcpAuthenticationError, match="profile_not_trusted"):
        _verifier(_identity(custody)).verify(request)


def test_rejects_a_key_that_is_not_published_by_the_trusted_profile() -> None:
    """Catches acceptance of a valid signature from a key outside the profile's keys[] set."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    custody.generate_es256("other-key")
    request = _valid_request(custody, key_id="other-key")

    with pytest.raises(UcpAuthenticationError, match="key_not_found"):
        _verifier(_identity(custody)).verify(request)


def test_rejects_a_digest_created_from_reserialized_json_bytes() -> None:
    """Catches verification performed on a reparsed JSON document rather than the wire bytes."""
    custody = KeyCustodyService()
    custody.generate_es256("agent-key")
    request = _valid_request(custody).with_header(
        "content-digest", "sha-256=:aW52YWxpZA==:"
    )
    request = request.with_header(
        "signature", f"sig1=:{base64.b64encode(custody.sign_es256('agent-key', signature_base(request))).decode('ascii')}:"
    )

    with pytest.raises(UcpAuthenticationError, match="content_digest_invalid"):
        _verifier(_identity(custody)).verify(request)

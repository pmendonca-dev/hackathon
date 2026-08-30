"""The protocol lane refuses a signature it has already seen, and a stale one.

The authorization lane has always required `created` and a nonce. The protocol lane —
UCP checkout, ACP delegation, capture, revocation, audit — required neither, so a
signature it once emitted authenticated forever: anyone who read it out of a log, a
proxy or a packet capture could send it again, unchanged, next week.

Both lanes now answer the same way, off the same clock and the same nonce memory.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from aval.adapters.ucp.http_signatures import (
    Rfc9421Verifier,
    SignedRequest,
    UcpAuthenticationError,
    signature_base,
)
from aval.domain.entities import AgentIdentity
from aval.security.content_digest import content_digest_sha256
from aval.security.http_signature import ReplayGuard
from aval.security.key_custody import KeyCustodyService

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
PROFILE = "https://agent.example/.well-known/ucp"


class TrustedRegistry:
    def __init__(self, identity: AgentIdentity) -> None:
        self._identity = identity

    def resolve(self, profile_url: str) -> AgentIdentity | None:
        return self._identity if profile_url == self._identity.profile_url else None


def _signed(
    custody: KeyCustodyService, *, created: int, nonce: str | None = None
) -> SignedRequest:
    body = json.dumps({"id": "chi_1"}).encode()
    covered = (
        'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
        '"content-digest" "content-type");keyid="agent-key";alg="ES256"'
        f';created={created};nonce="{nonce or secrets.token_hex(8)}"'
    )
    request = SignedRequest(
        method="POST",
        authority="merchant.example",
        path="/checkout-sessions",
        headers={
            "ucp-agent": f'profile="{PROFILE}"',
            "idempotency-key": "idem-1",
            "content-digest": content_digest_sha256(body),
            "content-type": "application/json",
            "signature-input": covered,
        },
        body=body,
    )
    signature = custody.sign_es256("agent-key", signature_base(request))
    return request.with_header(
        "signature", f"sig1=:{base64.b64encode(signature).decode('ascii')}:"
    )


@pytest.fixture
def custody() -> KeyCustodyService:
    service = KeyCustodyService()
    service.generate_es256("agent-key")
    return service


@pytest.fixture
def verifier(custody: KeyCustodyService) -> Rfc9421Verifier:
    identity = AgentIdentity(
        id="agent_1", profile_url=PROFILE, public_jwk=custody.public_jwk("agent-key"), trusted=True
    )
    return Rfc9421Verifier(TrustedRegistry(identity), clock=lambda: NOW, seen=ReplayGuard())


def test_the_same_signed_request_is_refused_the_second_time(custody, verifier) -> None:
    request = _signed(custody, created=int(NOW.timestamp()))

    assert verifier.verify(request).id == "agent_1"

    with pytest.raises(UcpAuthenticationError, match="signature_replayed"):
        verifier.verify(request)


def test_a_signature_from_outside_the_window_is_refused(custody, verifier) -> None:
    stale = _signed(custody, created=int((NOW - timedelta(hours=2)).timestamp()))

    with pytest.raises(UcpAuthenticationError, match="signature_stale"):
        verifier.verify(stale)


def test_a_signature_stamped_in_the_future_is_refused(custody, verifier) -> None:
    ahead = _signed(custody, created=int((NOW + timedelta(hours=2)).timestamp()))

    with pytest.raises(UcpAuthenticationError, match="signature_stale"):
        verifier.verify(ahead)


def test_a_signature_input_without_the_freshness_stamp_is_refused(custody, verifier) -> None:
    """The old wire format — no `created`, no nonce — is no longer accepted."""
    body = json.dumps({"id": "chi_1"}).encode()
    covered = (
        'sig1=("@method" "@authority" "@path" "ucp-agent" "idempotency-key" '
        '"content-digest" "content-type");keyid="agent-key";alg="ES256"'
    )
    request = SignedRequest(
        method="POST",
        authority="merchant.example",
        path="/checkout-sessions",
        headers={
            "ucp-agent": f'profile="{PROFILE}"',
            "idempotency-key": "idem-1",
            "content-digest": content_digest_sha256(body),
            "content-type": "application/json",
            "signature-input": covered,
        },
        body=body,
    )
    # The format is refused before the signature is ever looked at, so any well-formed
    # signature value will do here.
    request = request.with_header(
        "signature", "sig1=:" + base64.b64encode(b"\x00" * 64).decode("ascii") + ":"
    )

    with pytest.raises(UcpAuthenticationError, match="signature_input_invalid"):
        verifier.verify(request)


def test_two_distinct_requests_from_one_agent_both_pass(custody, verifier) -> None:
    """The guard must refuse a replay without refusing an honest second call."""
    assert verifier.verify(_signed(custody, created=int(NOW.timestamp()))).id == "agent_1"
    assert verifier.verify(_signed(custody, created=int(NOW.timestamp()))).id == "agent_1"


def test_an_unverified_signature_cannot_burn_a_real_nonce(custody, verifier) -> None:
    """Garbage signed by nobody must not spend the nonce the real agent is about to use."""
    nonce = secrets.token_hex(8)
    forged = _signed(custody, created=int(NOW.timestamp()), nonce=nonce).with_header(
        "signature", "sig1=:" + base64.b64encode(b"\x00" * 64).decode("ascii") + ":"
    )
    with pytest.raises(UcpAuthenticationError, match="signature_invalid"):
        verifier.verify(forged)

    genuine = _signed(custody, created=int(NOW.timestamp()), nonce=nonce)
    assert verifier.verify(genuine).id == "agent_1"

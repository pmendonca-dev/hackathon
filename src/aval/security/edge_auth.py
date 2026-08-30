"""The shared secret between the two computers, and nothing more.

The real-offer MVP splits the system in half. Computer A holds the Telegram token and
the OpenAI key and can reach the public web; Computer B holds the database, the signing
keys and the Stripe secret. Neither may hold the other's credentials, so they cannot
share a process — they share an HTTP hop instead.

That hop needs an authenticator, and deliberately **not** the RFC 9421 machinery in
`http_signature.py`. Those signatures carry *spending* authority: they say an agent
asked for a purchase, and the core reads them to decide whether money moves. This one
carries none. It says only "the process on the other computer sent this", which is why
a symmetric secret is the honest primitive: neither side can produce a mandate, an
authorization or a capture with it, so a leak here cannot move a cent.

What it must still do is bind the request completely. Method, path, timestamp and a
digest of the body all enter the canonical string, so a captured discovery signature
cannot be replayed onto the event outbox, and a body cannot be edited under a signature
that stays valid. See [[security-is-a-standing-constraint]]: the question for any new
surface is who can call it and what it can change.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from datetime import datetime

TIMESTAMP_HEADER = "X-Aval-Edge-Timestamp"
SIGNATURE_HEADER = "X-Aval-Edge-Signature"

# How far apart the two computers' clocks may be. Wide enough that two laptops without
# NTP still talk, narrow enough that a captured header pair stops working in minutes.
FRESHNESS_SECONDS = 300


class EdgeAuthError(Exception):
    """This request did not come from the other computer, or did not come intact."""


def _canonical(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    """What both sides sign.

    The body enters as a digest rather than whole: the value is fixed-length, so no
    field can be lengthened to swallow the next one, and a large discovery response
    does not have to be held twice.
    """
    return b"\n".join(
        [
            method.upper().encode("ascii"),
            path.encode("utf-8"),
            timestamp.encode("ascii"),
            hashlib.sha256(body).hexdigest().encode("ascii"),
        ]
    )


def _signature(secret: str, method: str, path: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"), _canonical(method, path, timestamp, body), hashlib.sha256
    ).hexdigest()


def _require_secret(secret: str) -> str:
    """An unset environment variable is an empty string, and both sides would agree on
    it. Refusing here is what turns a forgotten variable into a loud failure instead of
    an endpoint anyone can call."""
    cleaned = (secret or "").strip()
    if not cleaned:
        raise EdgeAuthError("edge secret is not configured")
    return cleaned


class EdgeSigner:
    """Signs one direction's requests. Each direction gets its own instance and secret,
    so a compromise of the discovery edge cannot read the event outbox."""

    def __init__(self, secret: str, *, clock: Callable[[], datetime]) -> None:
        self._secret = _require_secret(secret)
        self._clock = clock

    def sign(self, method: str, path: str, body: bytes) -> dict[str, str]:
        timestamp = str(int(self._clock().timestamp()))
        return {
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: _signature(self._secret, method, path, timestamp, body),
        }


def verify_edge_request(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    now: datetime,
) -> None:
    """Raise unless this request was signed for exactly this method, path and body."""
    checked = _require_secret(secret)
    lookup = {name.lower(): value for name, value in headers.items()}
    timestamp = (lookup.get(TIMESTAMP_HEADER.lower()) or "").strip()
    presented = (lookup.get(SIGNATURE_HEADER.lower()) or "").strip()
    if not timestamp or not presented:
        raise EdgeAuthError("edge signature headers are missing")
    try:
        sent_at = int(timestamp)
    except ValueError as error:
        raise EdgeAuthError("edge timestamp is not an integer") from error
    # Symmetric on purpose: a replay from the past and a computer whose clock runs ahead
    # are the same failure, and accepting either would widen the window a captured
    # header pair stays usable.
    if abs(int(now.timestamp()) - sent_at) > FRESHNESS_SECONDS:
        raise EdgeAuthError("edge request is outside the freshness window")
    if not hmac.compare_digest(_signature(checked, method, path, timestamp, body), presented):
        raise EdgeAuthError("edge signature does not match this request")

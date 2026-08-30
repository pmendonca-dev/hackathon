"""The signature that separates the two computers.

Computer A holds the Telegram and OpenAI credentials; Computer B holds the database,
the signing keys and Stripe. They talk over ordinary HTTP, which means the only thing
standing between B's private endpoints and the open internet is this HMAC. So the
tests below are not about the happy path — they are about every way a request can be
wrong and still look plausible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aval.security.edge_auth import (
    EdgeAuthError,
    EdgeSigner,
    verify_edge_request,
)

SECRET = "edge-secret"
NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def signer(now: datetime = NOW) -> EdgeSigner:
    return EdgeSigner(SECRET, clock=lambda: now)


def test_hmac_signature_binds_method_path_and_body() -> None:
    body = b'{"query":"switch"}'
    headers = signer().sign("POST", "/edge/v1/discover", body)
    verify_edge_request(SECRET, "POST", "/edge/v1/discover", body, headers, NOW)


def test_stale_or_modified_requests_are_rejected() -> None:
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    with pytest.raises(EdgeAuthError):
        verify_edge_request(
            SECRET, "POST", "/edge/v1/discover", b'{"changed":true}', headers, NOW
        )


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/edge/v1/discover"), ("POST", "/edge/v1/events")],
)
def test_a_signature_does_not_travel_to_another_route(method: str, path: str) -> None:
    """Replaying a discovery signature onto the event outbox must fail.

    Without method and path in the canonical string, one captured header pair would
    authenticate every endpoint on the other computer.
    """
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    with pytest.raises(EdgeAuthError):
        verify_edge_request(SECRET, method, path, b"{}", headers, NOW)


def test_the_other_directions_credential_is_not_accepted() -> None:
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    with pytest.raises(EdgeAuthError):
        verify_edge_request("core-secret", "POST", "/edge/v1/discover", b"{}", headers, NOW)


@pytest.mark.parametrize("drift", [timedelta(seconds=301), timedelta(seconds=-301)])
def test_requests_outside_the_freshness_window_are_rejected(drift: timedelta) -> None:
    """Old replays and clocks running ahead are the same problem in both directions."""
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    with pytest.raises(EdgeAuthError):
        verify_edge_request(SECRET, "POST", "/edge/v1/discover", b"{}", headers, NOW + drift)


@pytest.mark.parametrize("drift", [timedelta(seconds=299), timedelta(seconds=-299)])
def test_small_clock_drift_between_the_computers_is_tolerated(drift: timedelta) -> None:
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    verify_edge_request(SECRET, "POST", "/edge/v1/discover", b"{}", headers, NOW + drift)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Aval-Edge-Timestamp": "1756555200"},
        {"X-Aval-Edge-Signature": "deadbeef"},
        {"X-Aval-Edge-Timestamp": "not-a-number", "X-Aval-Edge-Signature": "deadbeef"},
        {"X-Aval-Edge-Timestamp": "", "X-Aval-Edge-Signature": ""},
    ],
)
def test_missing_or_malformed_headers_are_rejected(headers: dict[str, str]) -> None:
    with pytest.raises(EdgeAuthError):
        verify_edge_request(SECRET, "POST", "/edge/v1/discover", b"{}", headers, NOW)


def test_header_lookup_is_case_insensitive() -> None:
    """Starlette lowercases header names; a dict from a test does not."""
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    lowered = {name.lower(): value for name, value in headers.items()}
    verify_edge_request(SECRET, "POST", "/edge/v1/discover", b"{}", lowered, NOW)


def test_an_empty_secret_can_never_authenticate() -> None:
    """A deployment that forgot to configure the edge must be closed, not open.

    Empty-string secrets are what an unset environment variable produces, and both
    sides would agree on them — which is exactly the failure that must not be silent.
    """
    with pytest.raises(EdgeAuthError):
        EdgeSigner("", clock=lambda: NOW)
    with pytest.raises(EdgeAuthError):
        verify_edge_request("", "POST", "/edge/v1/discover", b"{}", {}, NOW)


def test_the_signature_never_contains_the_secret() -> None:
    headers = signer().sign("POST", "/edge/v1/discover", b"{}")
    assert SECRET not in "".join(headers.values())

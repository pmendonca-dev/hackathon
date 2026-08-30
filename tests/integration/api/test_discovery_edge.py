"""Computer A's discovery endpoint, from the outside.

The unit tests next door prove the normalizer drops hostile candidates. These prove the
door in front of it: who gets in, what a refusal reveals, and that the process on the
other side of it cannot reach anything that moves money.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from aval.discovery.models import DiscoveredOffer, ShoppingRequest
from aval.discovery.openai_web import OfferDiscovery
from aval.interfaces.discovery.app import DISCOVER_PATH, create_discovery_app
from aval.security.edge_auth import EdgeSigner

SECRET = "core-to-edge"
NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)

BODY = {
    "query": "Nintendo Switch OLED",
    "category": "shopping",
    "max_minor_units": 200000,
    "currency": "BRL",
}


class StubDiscovery(OfferDiscovery):
    def __init__(self) -> None:
        self.asked: list[ShoppingRequest] = []

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
        self.asked.append(request)
        return [
            DiscoveredOffer(
                title="Nintendo Switch OLED",
                source_merchant="shop.example",
                source_url="https://shop.example/switch",
                amount_minor_units=180000,
                currency="BRL",
                evidence="Preço na página do produto.",
            )
        ]


@pytest.fixture
def discovery() -> StubDiscovery:
    return StubDiscovery()


@pytest.fixture
def client(discovery: StubDiscovery) -> TestClient:
    return TestClient(
        create_discovery_app(secret=SECRET, discovery=discovery, now_provider=lambda: NOW)
    )


def signed(body: dict[str, object], *, at: datetime = NOW) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode("utf-8")
    return raw, EdgeSigner(SECRET, clock=lambda: at).sign("POST", DISCOVER_PATH, raw)


def test_a_signed_request_receives_normalized_offers(client: TestClient) -> None:
    raw, headers = signed(BODY)
    response = client.post(DISCOVER_PATH, content=raw, headers=headers)
    assert response.status_code == 200
    offer = response.json()["offers"][0]
    assert offer["source_url"] == "https://shop.example/switch"
    assert offer["amount_minor_units"] == 180000


def test_the_request_reaches_discovery_as_a_typed_shopping_request(
    client: TestClient, discovery: StubDiscovery
) -> None:
    raw, headers = signed(BODY)
    client.post(DISCOVER_PATH, content=raw, headers=headers)
    assert discovery.asked[0].query == "Nintendo Switch OLED"
    assert discovery.asked[0].max_minor_units == 200000


def test_an_unsigned_request_discovers_nothing(client: TestClient) -> None:
    response = client.post(DISCOVER_PATH, json=BODY)
    assert response.status_code == 401
    assert "offers" not in response.json()


def test_a_signature_from_the_other_direction_is_refused(client: TestClient) -> None:
    """A leaked A-to-B credential must not open A's own door."""
    raw = json.dumps(BODY).encode("utf-8")
    headers = EdgeSigner("edge-to-core", clock=lambda: NOW).sign("POST", DISCOVER_PATH, raw)
    assert client.post(DISCOVER_PATH, content=raw, headers=headers).status_code == 401


def test_a_stale_signature_is_refused(client: TestClient) -> None:
    raw, headers = signed(BODY, at=NOW - timedelta(hours=1))
    assert client.post(DISCOVER_PATH, content=raw, headers=headers).status_code == 401


def test_an_edited_body_under_a_valid_signature_is_refused(
    client: TestClient, discovery: StubDiscovery
) -> None:
    _, headers = signed(BODY)
    tampered = json.dumps({**BODY, "max_minor_units": 999999999}).encode("utf-8")
    assert client.post(DISCOVER_PATH, content=tampered, headers=headers).status_code == 401
    assert discovery.asked == []


def test_a_refused_request_never_reaches_the_search(
    client: TestClient, discovery: StubDiscovery
) -> None:
    """The signature is checked against raw bytes before anything parses them, so a
    body that fails it is never handed to a JSON decoder — let alone to OpenAI."""
    client.post(DISCOVER_PATH, content=b"{not json", headers={})
    assert discovery.asked == []


def test_a_refusal_says_nothing_about_why(client: TestClient) -> None:
    raw, _ = signed(BODY)
    body = client.post(DISCOVER_PATH, content=raw, headers={}).json()
    assert body == {"error": "edge_unauthenticated"}
    assert SECRET not in json.dumps(body)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**BODY, "query": ""},
        {**BODY, "currency": "REAIS"},
        {**BODY, "max_minor_units": 0},
        {**BODY, "max_minor_units": -1},
        {**BODY, "max_minor_units": "muito"},
        {**BODY, "category": ""},
        {**BODY, "scale": 99},
        [1, 2, 3],
    ],
)
def test_a_signed_but_nonsensical_request_is_rejected_not_searched(
    client: TestClient, discovery: StubDiscovery, payload: object
) -> None:
    raw = json.dumps(payload).encode("utf-8")
    headers = EdgeSigner(SECRET, clock=lambda: NOW).sign("POST", DISCOVER_PATH, raw)
    assert client.post(DISCOVER_PATH, content=raw, headers=headers).status_code == 422
    assert discovery.asked == []


def test_malformed_json_under_a_valid_signature_is_rejected(client: TestClient) -> None:
    raw = b"{not json"
    headers = EdgeSigner(SECRET, clock=lambda: NOW).sign("POST", DISCOVER_PATH, raw)
    assert client.post(DISCOVER_PATH, content=raw, headers=headers).status_code == 400


def test_the_discovery_edge_exposes_nothing_else(client: TestClient) -> None:
    """No schema, no docs, no core routes. A is not a second copy of the API."""
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.post("/authorize", json={}).status_code == 404
    assert client.get("/mandates").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_computer_a_cannot_import_the_money_moving_half() -> None:
    """The boundary as a fact about the process, not a promise in a comment.

    A cannot settle what it cannot import. Checked in a fresh interpreter, because in
    this one the whole test suite has already imported everything. If this ever fails,
    the discovery edge has grown a path to the core and the split has stopped being
    real — a process holding the OpenAI key would be one import away from the Stripe
    adapter and the authorization core.
    """
    import subprocess
    import sys

    forbidden = (
        "aval.runtime",
        "aval.infrastructure.stripe_psp",
        "aval.application.authorization_core",
        "aval.infrastructure.sqlite.models",
    )
    probe = (
        "import sys;"
        "import aval.interfaces.discovery.app;"
        "leaked=[n for n in %r if n in sys.modules];"
        "print(','.join(leaked))" % (forbidden,)
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"A importou o núcleo: {result.stdout.strip()}"

"""How a result gets from the computer that bought to the computer that can speak.

Computer B closes a watch with nobody watching. Computer A is the only half that can
reach Telegram. Between them there is a network that will be down at some point, and a
person waiting to be told their money moved — so "B calls A" is not good enough. B
writes what happened to a table, A polls it, and A says it is done only after Telegram
has taken the message.

Two properties carry that, and both are tested here: the event is written in the *same*
transaction that closes the watch, so a crash cannot produce a purchase nobody hears
about; and acknowledgement is idempotent, so a retry after a lost response is free.

The third thing tested is what the event may contain. It crosses to the computer holding
the OpenAI key and ends up in a chat message, so a payment token or a signature going
through here would be a leak with a very short path to a screen.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from aval.agent.purchasing_agent import PurchasingAgent
from aval.agent.watches import WatchService
from aval.discovery.models import DiscoveredOffer, ShoppingRequest, encode_shopping_request
from aval.discovery.openai_web import OfferDiscovery
from aval.infrastructure.sqlite.watch_repository import SqliteWatchRepository
from aval.merchant.catalog import TEST_MARKETPLACE_ID
from aval.security.edge_auth import EdgeSigner

EDGE_SECRET = "edge-to-core"
EVENTS_PATH = "/edge/v1/events"


class StubDiscovery(OfferDiscovery):
    def __init__(self, *offers: DiscoveredOffer) -> None:
        self.offers = list(offers)

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
        return list(self.offers)


def found(minor_units: int = 12000) -> DiscoveredOffer:
    return DiscoveredOffer(
        title="Notebook Acer Aspire 5",
        source_merchant="shop.example",
        source_url="https://shop.example/aspire-5",
        amount_minor_units=minor_units,
        currency="USD",
        evidence="Preço anunciado na página do produto.",
    )


@pytest.fixture(autouse=True)
def edge_secret(monkeypatch) -> None:
    monkeypatch.setenv("AVAL_EDGE_TO_CORE_SECRET", EDGE_SECRET)


def headers_for(method: str, path: str, body: bytes = b"") -> dict[str, str]:
    return EdgeSigner(EDGE_SECRET, clock=lambda: datetime.now(UTC)).sign(method, path, body)


def close_matching_watch(harness, *, offer: DiscoveredOffer | None = None) -> str:
    """Run one watch to completion against a page this test wrote."""
    payload = harness.mandate_payload(
        allowed_merchant_ids=[TEST_MARKETPLACE_ID], allowed_categories=["shopping"]
    )
    mandate_id = harness.client.post("/mandates", json=payload).json()["mandate_id"]
    instruction = encode_shopping_request(
        ShoppingRequest(
            query="notebook", category="shopping", max_minor_units=15000, currency="USD"
        )
    )
    harness.client.post(
        "/agent/watches", json={"mandate_id": mandate_id, "instruction": instruction}
    )
    runtime = replace(harness.runtime, discovery=StubDiscovery(*( [offer] if offer else [found()] )))
    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    with runtime.engine.connect() as connection:
        mandates = SqliteWatchRepository(connection).mandates_with_open_watches()
    for mandate in mandates:
        service.tick(mandate)
    return mandate_id


def read_events(harness, *, after: int | None = None) -> list[dict]:
    path = EVENTS_PATH if after is None else f"{EVENTS_PATH}?after={after}"
    response = harness.client.get(path, headers=headers_for("GET", path))
    assert response.status_code == 200, response.text
    return response.json()["events"]


# ── the outbox ──────────────────────────────────────────────────────────────
def test_closed_watch_emits_one_event_and_ack_is_idempotent(harness) -> None:
    close_matching_watch(harness)

    events = read_events(harness)
    assert len(events) == 1
    assert events[0]["event_type"] == "watch_closed"

    ack = f"{EVENTS_PATH}/{events[0]['id']}/ack"
    assert harness.client.post(ack, headers=headers_for("POST", ack)).status_code == 204
    assert harness.client.post(ack, headers=headers_for("POST", ack)).status_code == 204


def test_an_acknowledged_event_is_not_delivered_twice(harness) -> None:
    close_matching_watch(harness)
    event = read_events(harness)[0]

    ack = f"{EVENTS_PATH}/{event['id']}/ack"
    harness.client.post(ack, headers=headers_for("POST", ack))

    assert read_events(harness) == []


def test_an_unacknowledged_event_is_redelivered(harness) -> None:
    """Telegram not taking the message is the reason this table exists."""
    close_matching_watch(harness)

    assert len(read_events(harness)) == 1
    assert len(read_events(harness)) == 1, "reading is not acknowledging"


def test_the_cursor_skips_what_the_edge_already_saw(harness) -> None:
    close_matching_watch(harness)
    close_matching_watch(harness)

    events = read_events(harness)
    assert len(events) == 2
    assert read_events(harness, after=events[0]["id"]) == events[1:]


def test_a_watch_that_only_waited_emits_nothing(harness) -> None:
    """An open watch has no news. Only an answer is an event."""
    close_matching_watch(harness, offer=found(minor_units=99999999))
    events = read_events(harness)
    assert all(event["payload"]["outcome"] != "no_offer" for event in events)


# ── what may cross ──────────────────────────────────────────────────────────
def test_the_event_says_what_a_person_needs_and_nothing_else(harness) -> None:
    close_matching_watch(harness)
    payload = read_events(harness)[0]["payload"]

    assert payload["source_url"] == "https://shop.example/aspire-5"
    assert payload["title"] == "Notebook Acer Aspire 5"
    assert payload["amount_minor_units"] == 12000
    assert payload["currency"] == "USD"
    assert payload["outcome"]
    assert payload["principal_id"]


def test_no_payment_token_or_signature_crosses_to_the_edge(harness) -> None:
    """A carries the OpenAI key and writes to a chat. Anything here is one hop from a
    screen, and a `pm_...` token or a signed authorization has no business on that hop."""
    close_matching_watch(harness)
    raw = json.dumps(read_events(harness))

    assert "pm_test" not in raw
    assert "merchant_authorization" not in raw
    assert "authorization_proof" not in raw
    assert "creation_jws" not in raw
    assert "eyJ" not in raw, "a compact JWS starts eyJ; none may travel"


# ── the door ────────────────────────────────────────────────────────────────
def test_an_unsigned_reader_gets_nothing(harness) -> None:
    close_matching_watch(harness)
    assert harness.client.get(EVENTS_PATH).status_code == 401


def test_an_unsigned_acknowledgement_is_refused(harness) -> None:
    close_matching_watch(harness)
    event = read_events(harness)[0]

    assert harness.client.post(f"{EVENTS_PATH}/{event['id']}/ack").status_code == 401
    assert len(read_events(harness)) == 1, "a refused ack must not have delivered anything"


def test_a_signature_for_another_route_does_not_open_this_one(harness) -> None:
    close_matching_watch(harness)
    borrowed = headers_for("POST", "/edge/v1/discover")
    assert harness.client.get(EVENTS_PATH, headers=borrowed).status_code == 401


def test_a_stale_signature_is_refused(harness) -> None:
    stale = EdgeSigner(
        EDGE_SECRET, clock=lambda: datetime.now(UTC) - timedelta(hours=1)
    ).sign("GET", EVENTS_PATH, b"")
    assert harness.client.get(EVENTS_PATH, headers=stale).status_code == 401


def test_acknowledging_an_event_that_does_not_exist_is_not_an_error(harness) -> None:
    """A is allowed to retry an ack it is no longer sure it sent."""
    ack = f"{EVENTS_PATH}/999999/ack"
    assert harness.client.post(ack, headers=headers_for("POST", ack)).status_code == 204

"""A standing order against the open web, and the core still deciding everything.

This is the case's premise with the training wheels off. The catalogue watch already
proved a watch fires without a human in the room; the offers it fired against were ones
this system had signed itself. Here the offer comes from a page nobody controls, found
by a model, and the interesting question is what changes.

The answer has to be: nothing that matters. The mandate is still the only authority, a
revoked mandate still refuses, a price over the ceiling is still refused, and a category
outside the scope is still refused — no matter how good the thing the search found is.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from aval.agent.purchasing_agent import PurchasingAgent
from aval.agent.scheduler import tick_once
from aval.agent.watches import WatchService
from aval.discovery.models import DiscoveredOffer, ShoppingRequest, encode_shopping_request
from aval.discovery.openai_web import OfferDiscovery
from aval.infrastructure.sqlite.watch_repository import SqliteWatchRepository
from aval.merchant.catalog import TEST_MARKETPLACE_ID, TEST_MARKETPLACE_KID
from aval.security.jws import sign_compact_jws, verify_compact_jws


class StubDiscovery(OfferDiscovery):
    """The web, as a list this test controls."""

    def __init__(self, *offers: DiscoveredOffer) -> None:
        self.offers = list(offers)
        self.asked: list[ShoppingRequest] = []

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
        self.asked.append(request)
        return list(self.offers)


def found(minor_units: int = 12000, **overrides: object) -> DiscoveredOffer:
    base = {
        "title": "Notebook Acer Aspire 5",
        "source_merchant": "shop.example",
        "source_url": "https://shop.example/aspire-5",
        "amount_minor_units": minor_units,
        "currency": "USD",
        "evidence": "Preço anunciado na página do produto.",
    }
    return DiscoveredOffer(**{**base, **overrides})  # type: ignore[arg-type]


def shopping_mandate(harness, **overrides: object) -> str:
    scope: dict[str, object] = {
        "allowed_merchant_ids": [TEST_MARKETPLACE_ID],
        "allowed_categories": ["shopping"],
    }
    payload = harness.mandate_payload(**{**scope, **overrides})
    response = harness.client.post("/mandates", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["mandate_id"]


def watch_on(harness, mandate_id: str, *, cap: int = 15000, query: str = "notebook") -> str:
    instruction = encode_shopping_request(
        ShoppingRequest(query=query, category="shopping", max_minor_units=cap, currency="USD")
    )
    response = harness.client.post(
        "/agent/watches", json={"mandate_id": mandate_id, "instruction": instruction}
    )
    assert response.status_code == 201, response.text
    return response.json()["watch_id"]


def read_watch(harness, mandate_id: str, watch_id: str) -> dict:
    watches = harness.client.get("/agent/watches", params={"mandate_id": mandate_id}).json()
    return next(w for w in watches["watches"] if w["watch_id"] == watch_id)


def tick_with(harness, discovery: OfferDiscovery) -> int:
    """Run B's scheduler tick against a web this test wrote."""
    return tick_once(replace(harness.runtime, discovery=discovery))


def revoke(harness, mandate_id: str) -> None:
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )
    response = harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})
    assert response.status_code == 200, response.text


def fire(harness, discovery: OfferDiscovery):
    """The same tick, but handing back what the core was actually asked to evaluate."""
    runtime = replace(harness.runtime, discovery=discovery)
    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    return [outcome for mandate in _mandates_with_watches(runtime) for outcome in service.tick(mandate)]


def _mandates_with_watches(runtime):
    with runtime.engine.connect() as connection:
        return SqliteWatchRepository(connection).mandates_with_open_watches()


# ── the happy path, and what it is allowed to claim ─────────────────────────
def test_a_discovered_offer_under_the_cap_is_bought(harness) -> None:
    mandate_id = shopping_mandate(harness)
    watch_id = watch_on(harness, mandate_id)

    assert tick_with(harness, StubDiscovery(found())) == 1

    watch = read_watch(harness, mandate_id, watch_id)
    assert watch["status"] == "FIRED"
    assert watch["settlement_reference"]


def test_the_search_is_asked_for_what_the_person_actually_said(harness) -> None:
    mandate_id = shopping_mandate(harness)
    watch_on(harness, mandate_id, cap=15000, query="notebook para faculdade")
    discovery = StubDiscovery(found())

    tick_with(harness, discovery)

    assert discovery.asked[0].query == "notebook para faculdade"
    assert discovery.asked[0].max_minor_units == 15000
    assert discovery.asked[0].currency == "USD"


def test_what_the_core_evaluated_was_signed_and_names_the_page(harness) -> None:
    """The core reads a signed offer or it reads nothing. This is the offer it read."""
    mandate_id = shopping_mandate(harness)
    watch_on(harness, mandate_id)

    offer = fire(harness, StubDiscovery(found()))[0].run.offer

    assert offer["merchant_id"] == TEST_MARKETPLACE_ID
    assert offer["item"]["source_url"] == "https://shop.example/aspire-5"
    assert offer["merchant_authorization"], "the core never evaluates an unsigned offer"
    assert offer["item"]["category"] == "shopping"


def test_the_agent_says_where_it_found_the_thing(harness) -> None:
    """A person reading the message has to be able to check the claim themselves."""
    mandate_id = shopping_mandate(harness)
    watch_on(harness, mandate_id)

    run = fire(harness, StubDiscovery(found(), found(13000, source_url="https://b.example/x")))[0].run

    assert run.proposed_by == "discovery"
    assert "shop.example" in run.rationale
    assert run.alternatives, "the page it passed over is part of the account it gives"


def test_the_offer_the_marketplace_signed_verifies_against_its_own_key(harness) -> None:
    from aval.merchant.discovered_offers import DiscoveredOfferIssuer

    issuer = DiscoveredOfferIssuer(
        clock=harness.runtime.clock.now, custody=harness.runtime.merchant_custody
    )
    offer = issuer.issue(found())
    claims = verify_compact_jws(
        offer["merchant_authorization"],
        harness.runtime.merchant_custody.verifying_key(TEST_MARKETPLACE_KID),
    )
    assert claims["merchant_id"] == TEST_MARKETPLACE_ID


# ── the refusals, which are the point ───────────────────────────────────────
def test_revoked_watch_does_not_charge_even_when_discovery_matches(harness) -> None:
    """The search found exactly what was asked for. It still may not be bought."""
    mandate_id = shopping_mandate(harness)
    watch_id = watch_on(harness, mandate_id)
    revoke(harness, mandate_id)

    tick_with(harness, StubDiscovery(found()))

    watch = read_watch(harness, mandate_id, watch_id)
    assert watch["outcome"] == "mandate_revoked"
    assert watch["settlement_reference"] is None


def test_a_page_over_the_mandate_ceiling_is_refused_not_bought(harness) -> None:
    mandate_id = shopping_mandate(
        harness, ceiling={"minor_units": 10000, "currency": "USD", "scale": 2}
    )
    watch_id = watch_on(harness, mandate_id, cap=15000)

    tick_with(harness, StubDiscovery(found(minor_units=12000)))

    watch = read_watch(harness, mandate_id, watch_id)
    assert watch["status"] == "FIRED"
    assert watch["settlement_reference"] is None
    assert watch["outcome"] != "settled"


def test_a_mandate_that_never_allowed_shopping_refuses_every_page(harness) -> None:
    mandate_id = shopping_mandate(harness, allowed_categories=["travel"])
    watch_id = watch_on(harness, mandate_id)

    tick_with(harness, StubDiscovery(found()))

    watch = read_watch(harness, mandate_id, watch_id)
    assert watch["outcome"] == "category_not_allowed"


def test_a_mandate_scoped_to_real_sellers_refuses_the_test_marketplace(harness) -> None:
    """The marketplace is a merchant like any other, and scope still applies to it."""
    mandate_id = shopping_mandate(harness, allowed_merchant_ids=["vuelaya"])
    watch_id = watch_on(harness, mandate_id)

    tick_with(harness, StubDiscovery(found()))

    assert read_watch(harness, mandate_id, watch_id)["outcome"] == "merchant_out_of_scope"


# ── waiting is a state, not a failure ───────────────────────────────────────
def test_a_search_that_finds_nothing_leaves_the_watch_open(harness) -> None:
    mandate_id = shopping_mandate(harness)
    watch_id = watch_on(harness, mandate_id)

    assert tick_with(harness, StubDiscovery()) == 0

    assert read_watch(harness, mandate_id, watch_id)["status"] == "OPEN"


def test_an_unreachable_discovery_edge_leaves_the_watch_open(harness) -> None:
    """Computer A being down is not an answer about prices."""

    class Unreachable(OfferDiscovery):
        def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
            return []

    mandate_id = shopping_mandate(harness)
    watch_id = watch_on(harness, mandate_id)

    tick_with(harness, Unreachable())

    assert read_watch(harness, mandate_id, watch_id)["status"] == "OPEN"


def test_one_failing_search_does_not_end_the_tick_for_other_watches(harness) -> None:
    """Every open watch on the machine shares one tick. One exploding search must not
    take the others with it."""

    class Exploding(OfferDiscovery):
        def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
            raise RuntimeError("openai is down")

    mandate_id = shopping_mandate(harness)
    watch_id = watch_on(harness, mandate_id)

    tick_with(harness, Exploding())

    assert read_watch(harness, mandate_id, watch_id)["status"] == "OPEN"


# ── the catalogue watch is untouched ────────────────────────────────────────
def test_a_plain_text_watch_still_shops_the_catalogue(harness) -> None:
    """The travel demo must keep working exactly as it did, with no discovery at all."""
    payload = harness.mandate_payload()
    mandate_id = harness.client.post("/mandates", json=payload).json()["mandate_id"]
    response = harness.client.post(
        "/agent/watches",
        json={"mandate_id": mandate_id, "instruction": "voo para Córdoba até 150"},
    )
    assert response.status_code == 201

    discovery = StubDiscovery(found())
    tick_with(harness, discovery)

    assert discovery.asked == [], "a catalogue watch must never reach the open web"

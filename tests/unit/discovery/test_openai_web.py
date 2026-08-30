"""What the open web is allowed to hand back.

Everything in this file is about one boundary. A discovery answer is written partly by
a language model and partly by whatever pages it read, so it is the least trustworthy
input the system takes. It is also the input that decides what a mandate gets asked to
pay for, which makes the normalizer the place where an untrusted string stops being a
string and becomes a number the core can refuse.

So the tests here are mostly about what gets *dropped*.
"""

from __future__ import annotations

from typing import Any

import pytest

from aval.discovery.models import DiscoveredOffer, ShoppingRequest
from aval.discovery.openai_web import OpenAIWebDiscovery

REQUEST = ShoppingRequest(
    query="Nintendo Switch OLED",
    category="shopping",
    max_minor_units=200000,
    currency="BRL",
)


def candidate(**overrides: Any) -> dict[str, Any]:
    base = {
        "title": "Nintendo Switch OLED",
        "merchant": "Mercado Livre",
        "url": "https://shop.example/switch",
        "price": 1800.00,
        "currency": "BRL",
        "evidence": "Anunciado por R$ 1.800,00 na página do produto.",
    }
    return {**base, **overrides}


def answer(*candidates: dict[str, Any]) -> dict[str, Any]:
    return {"offers": list(candidates)}


def discovery(response: Any) -> OpenAIWebDiscovery:
    return OpenAIWebDiscovery(responder=lambda _: response)


def test_response_with_url_price_and_evidence_becomes_a_candidate() -> None:
    offer = discovery(answer(candidate())).find(REQUEST)[0]
    assert offer.source_url == "https://shop.example/switch"
    assert offer.amount_minor_units == 180000
    assert offer.currency == "BRL"
    assert offer.evidence


@pytest.mark.parametrize(
    "broken",
    [
        {"url": "http://shop.example/switch"},
        {"url": "ftp://shop.example/switch"},
        {"url": "javascript:alert(1)"},
        {"url": "/switch"},
        {"url": ""},
        {"price": 0},
        {"price": -10},
        {"price": "muito barato"},
        {"price": None},
        {"evidence": ""},
        {"title": ""},
        {"currency": "USD"},
    ],
)
def test_candidate_without_https_url_or_positive_price_is_dropped(
    broken: dict[str, Any]
) -> None:
    assert discovery(answer(candidate(**broken))).find(REQUEST) == []


def test_a_candidate_over_the_cap_is_dropped_before_it_reaches_the_core() -> None:
    """The mandate would refuse it anyway. Dropping it here keeps the agent from
    proposing something the person already said is too expensive."""
    assert discovery(answer(candidate(price=2500.00))).find(REQUEST) == []


def test_a_candidate_exactly_at_the_cap_survives() -> None:
    assert discovery(answer(candidate(price=2000.00))).find(REQUEST)[0].amount_minor_units == 200000


def test_the_seller_shown_comes_from_the_url_not_from_the_model() -> None:
    """The model's `merchant` field contradicts its own URL in practice.

    Real answers from `gpt-4.1-mini` with web search named "Mercado Livre" beside a
    `gamehunter.com.br` link and "Shopee" beside `promotech.app.br`. Showing the claim
    would tell a buyer they are about to be sent somewhere they are not.
    """
    offer = discovery(
        answer(candidate(merchant="Mercado Livre", url="https://gamehunter.com.br/x"))
    ).find(REQUEST)[0]
    assert offer.source_merchant == "gamehunter.com.br"
    assert "Mercado Livre" not in offer.source_merchant


def test_tracking_parameters_are_stripped_from_the_url() -> None:
    """Every real answer came back tagged with `utm_source=openai`."""
    offer = discovery(
        answer(candidate(url="https://shop.example/switch?utm_source=openai&ref=abc"))
    ).find(REQUEST)[0]
    assert offer.source_url == "https://shop.example/switch"


def test_credentials_embedded_in_a_url_are_refused() -> None:
    assert discovery(answer(candidate(url="https://user:pw@shop.example/x"))).find(REQUEST) == []


def test_the_same_seller_page_is_only_offered_once() -> None:
    two = answer(candidate(), candidate(price=1900.00))
    assert len(discovery(two).find(REQUEST)) == 1


def test_at_most_five_candidates_survive() -> None:
    many = answer(*(candidate(url=f"https://shop.example/{n}") for n in range(12)))
    assert len(discovery(many).find(REQUEST)) == 5


def test_long_text_from_the_web_cannot_become_the_message() -> None:
    """A title is going into a Telegram message. It does not get to be a page."""
    offer = discovery(answer(candidate(title="x" * 5000, evidence="y" * 5000))).find(REQUEST)[0]
    assert len(offer.title) <= 200
    assert len(offer.evidence) <= 400


@pytest.mark.parametrize(
    "response",
    [
        None,
        "not an object",
        {},
        {"offers": "not a list"},
        {"offers": [None, 7, "x"]},
        {"offers": [{}]},
    ],
)
def test_a_malformed_answer_discovers_nothing(response: Any) -> None:
    assert discovery(response).find(REQUEST) == []


def test_a_failing_search_discovers_nothing_instead_of_raising() -> None:
    """A watch that cannot search has simply not found anything yet. It must not
    crash the scheduler tick that every other watch shares."""

    def explode(_: ShoppingRequest) -> Any:
        raise RuntimeError("openai is down")

    assert OpenAIWebDiscovery(responder=explode).find(REQUEST) == []


def test_a_discovered_offer_carries_no_authority() -> None:
    """It is data about the web, not a claim anyone signed."""
    offer = discovery(answer(candidate())).find(REQUEST)[0]
    assert isinstance(offer, DiscoveredOffer)
    assert not hasattr(offer, "merchant_authorization")
    assert not hasattr(offer, "terms_hash")

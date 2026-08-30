"""The two halves of the proposing agent, tested without a network.

`shortlist` is what a catalogue of thousands would be reduced to before anyone spends a
token on it; `propose` is everything that can go wrong between a model and a decision.
"""

from __future__ import annotations

import urllib.error

import pytest

from aval.agent import llm_proposer
from aval.agent.intent import parse_intent
from aval.agent.purchasing_agent import shortlist


def offer(sku: str, category: str, minor_units: int, *, title: str = "") -> dict:
    return {
        "merchant_id": "vuelaya",
        "item": {"sku": sku, "title": title or sku, "category": category, "stops": 0},
        "total": {"minor_units": minor_units, "currency": "USD", "scale": 2},
    }


CATALOG = [
    offer("FL-A", "travel", 11800, title="São Paulo → Córdoba, 2 escalas"),
    offer("FL-B", "travel", 13000, title="São Paulo → Córdoba, direto"),
    offer("FL-C", "travel", 90000, title="São Paulo → Córdoba, executiva"),
    offer("HT-A", "lodging", 22000, title="Hotel Córdoba Centro"),
]


def test_the_shortlist_drops_what_the_buyer_said_is_too_expensive():
    """The target price is the buyer being picky — the mandate's limits are elsewhere."""
    picked = shortlist(CATALOG, parse_intent("um voo pra Córdoba abaixo de $150"))

    assert [entry["item"]["sku"] for entry in picked] == ["FL-A", "FL-B"]


def test_the_shortlist_keeps_offers_the_rules_would_never_choose():
    """The hotel survives a flight request on purpose.

    A model that cannot see the out-of-scope offer can never be caught proposing it,
    and the escalation the case asks for would never have anything to fire on.
    """
    picked = shortlist(CATALOG, parse_intent("compre um voo pra Córdoba"))

    assert "HT-A" in [entry["item"]["sku"] for entry in picked]
    assert picked[0]["item"]["sku"] == "FL-A", "cheapest matching category still leads"


def test_the_shortlist_is_capped_but_never_silences_a_category():
    """The cap keeps the prompt small; the exception keeps the demo honest.

    Even when one category takes every slot, the best offer of the categories that lost
    still travels — otherwise the out-of-scope refusal could never be provoked.
    """
    picked = [entry["item"]["sku"] for entry in shortlist(CATALOG * 10, parse_intent("voo pra Córdoba"), limit=5)]

    assert picked.count("FL-A") == 5, "the cap holds for the category that was asked for"
    assert picked.count("HT-A") == 1, "and the category that lost still gets one seat"


@pytest.fixture
def answering(monkeypatch):
    monkeypatch.setenv("AVAL_LLM_API_KEY", "sk-test")

    def use(reply):
        def fake_post(payload, timeout):
            if isinstance(reply, Exception):
                raise reply
            return {"choices": [{"message": {"content": reply}}]}

        monkeypatch.setattr(llm_proposer, "_post", fake_post)

    return use


def test_a_well_formed_answer_becomes_a_proposal(answering):
    answering(
        '{"sku": "FL-B", "motivo": "Direto.",'
        ' "descartadas": [{"sku": "FL-A", "motivo": "19h"}], "excede_mandato": false}'
    )

    proposal = llm_proposer.propose("pra Córdoba", CATALOG)

    assert proposal.sku == "FL-B"
    assert proposal.rationale == "Direto."
    assert proposal.alternatives == (("FL-A", "19h"),)
    assert proposal.knows_it_exceeds is False


def test_an_invented_sku_is_not_a_proposal(answering):
    answering('{"sku": "FL-NOPE", "motivo": "Promoção que eu achei."}')

    assert llm_proposer.propose("pra Córdoba", CATALOG) is None


def test_prose_instead_of_json_is_not_a_proposal(answering):
    answering("Claro! Recomendo o voo direto das 10h45.")

    assert llm_proposer.propose("pra Córdoba", CATALOG) is None


def test_a_dead_network_is_not_a_proposal(answering):
    answering(urllib.error.URLError("no route to host"))

    assert llm_proposer.propose("pra Córdoba", CATALOG) is None


def test_a_slow_model_is_not_a_proposal(answering):
    answering(TimeoutError("timed out"))

    assert llm_proposer.propose("pra Córdoba", CATALOG) is None


def test_without_a_key_nothing_is_asked(monkeypatch):
    monkeypatch.delenv("AVAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert llm_proposer.configured() is False
    assert llm_proposer.propose("pra Córdoba", CATALOG) is None


def test_the_offer_the_model_reads_carries_what_the_seller_signed():
    """Whatever the model decides on must be an attribute the seller put its key behind."""
    line = llm_proposer._offer_line(
        {
            "merchant_id": "vuelaya",
            "item": {
                "sku": "FL-B",
                "title": "São Paulo → Córdoba",
                "category": "travel",
                "stops": 0,
                "duration_minutes": 185,
                "departs": "10:45",
                "checked_bag": True,
            },
            "total": {"minor_units": 13000, "currency": "USD", "scale": 2},
        }
    )

    assert "130.00 USD" in line
    assert "direto" in line and "3h05" in line and "parte 10:45" in line
    assert "com bagagem" in line

    hotel = llm_proposer._offer_line(
        {
            "merchant_id": "posadas",
            "item": {"sku": "HT-A", "title": "Hotel", "category": "lodging", "nights": 3},
            "total": {"minor_units": 22000, "currency": "USD", "scale": 2},
        }
    )

    assert "bagagem" not in hotel, "a hotel has no baggage to talk about"

"""The LLM sits in the proposing half, and nowhere else.

Swapping the rule proposer for a model changes what the agent *wants*. It changes
nothing about what may be bought, because the core never reads this text and never sees
the object it produces. These tests hold that line from three sides:

- `shortlist` is what a catalogue of thousands is reduced to before anyone spends a
  token on it, and it must keep the offers the rules would never choose;
- whatever the model returns is coerced into a `Proposal` naming an offer a seller
  actually signed, and a hostile or malformed answer falls back rather than propagating;
- the model is never told the mandate's limit, ceiling or balance, so a prompt-injected
  model has nothing to leak.
"""

from __future__ import annotations

import inspect

import pytest

from aval.agent.intent import parse_intent
from aval.agent.proposer import (
    ModelProposer,
    Proposal,
    Question,
    RuleProposer,
    build_proposer,
    offer_line,
    shortlist,
)


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


class FakeModel:
    """Stands in for the Anthropic client. Records what it was asked."""

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[tuple[str, list[dict]]] = []

    def __call__(self, instruction: str, candidates: list[dict]) -> object:
        self.calls.append((instruction, candidates))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


# ── the deterministic floor ─────────────────────────────────────────────────
def test_the_shortlist_drops_what_the_buyer_said_is_too_expensive() -> None:
    """The target price is the buyer being picky — the mandate's limits are elsewhere."""
    picked = shortlist(CATALOG, parse_intent("um voo pra Córdoba abaixo de $150"))

    assert [entry["item"]["sku"] for entry in picked] == ["FL-A", "FL-B"]


def test_the_shortlist_keeps_offers_the_rules_would_never_choose() -> None:
    """The hotel survives a flight request on purpose.

    A model that cannot see the out-of-scope offer can never be caught proposing it,
    and the escalation the case asks for would never have anything to fire on.
    """
    picked = shortlist(CATALOG, parse_intent("compre um voo pra Córdoba"))

    assert "HT-A" in [entry["item"]["sku"] for entry in picked]
    assert picked[0]["item"]["sku"] == "FL-A", "cheapest matching category still leads"


def test_the_shortlist_is_capped_but_never_silences_a_category() -> None:
    picked = shortlist(CATALOG * 10, parse_intent("voo pra Córdoba"), limit=5)
    skus = [entry["item"]["sku"] for entry in picked]

    assert len(skus) == 6, "the cap holds, plus one seat kept for the other category"
    assert "HT-A" in skus


def test_the_rule_proposer_needs_no_model_at_all() -> None:
    proposal = RuleProposer().propose("compre um voo pra Córdoba", CATALOG)

    assert proposal is not None
    assert proposal.offer["item"]["sku"] == "FL-A"
    assert proposal.proposed_by == "rules"


# ── the model ───────────────────────────────────────────────────────────────
def test_a_model_answer_becomes_a_proposal_naming_a_signed_offer() -> None:
    model = FakeModel(
        {
            "sku": "FL-B",
            "reason": "direto, e a diferença de doze dólares paga sete horas a menos.",
            "rejected": [{"sku": "FL-A", "reason": "duas escalas"}],
        }
    )

    proposal = ModelProposer(model).propose("um voo pra Córdoba", CATALOG)

    assert proposal == Proposal(
        offer=CATALOG[1],
        rationale="direto, e a diferença de doze dólares paga sete horas a menos.",
        alternatives=(("FL-A", "duas escalas"),),
        proposed_by="llm",
    )


def test_the_model_may_propose_the_offer_the_rules_never_would() -> None:
    """The whole point. The core is what refuses it, not the agent."""
    proposal = ModelProposer(
        FakeModel({"sku": "HT-A", "reason": "achei melhor um hotel", "rejected": []})
    ).propose("um voo pra Córdoba", CATALOG)

    assert proposal is not None
    assert proposal.offer["item"]["category"] == "lodging"


def test_a_model_timeout_falls_back_to_the_rules_instead_of_failing_the_purchase() -> None:
    """The stage version of this: no API key, a slow network, a rate limit. The demo
    must not depend on any of them."""
    proposal = ModelProposer(FakeModel(TimeoutError("upstream slow"))).propose(
        "compre um voo pra Córdoba", CATALOG
    )

    assert proposal == RuleProposer().propose("compre um voo pra Córdoba", CATALOG)


@pytest.mark.parametrize(
    "answer",
    [
        "não é um objeto",
        {"reason": "esqueci o sku", "rejected": []},
        {"sku": "FL-INEXISTENTE", "reason": "inventei", "rejected": []},
        {"sku": "FL-B", "reason": "ok", "rejected": "não é lista"},
    ],
    ids=["not-an-object", "no-sku", "invented-sku", "malformed-alternatives"],
)
def test_a_malformed_model_answer_falls_back_rather_than_propagating(answer: object) -> None:
    proposal = ModelProposer(FakeModel(answer)).propose("compre um voo pra Córdoba", CATALOG)

    assert proposal == RuleProposer().propose("compre um voo pra Córdoba", CATALOG)


def test_an_alternative_naming_an_unknown_sku_is_dropped_not_fatal() -> None:
    proposal = ModelProposer(
        FakeModel(
            {
                "sku": "FL-B",
                "reason": "direto",
                "rejected": [{"sku": "NAO-EXISTE", "reason": "?"}, {"sku": "FL-A", "reason": "escalas"}],
            }
        )
    ).propose("um voo pra Córdoba", CATALOG)

    assert proposal is not None
    assert proposal.alternatives == (("FL-A", "escalas"),)


def test_the_model_is_never_handed_the_mandate() -> None:
    """A model told the budget could be talked into repeating it. This one is not told.

    The signature is the guarantee — there is no parameter for a limit, a ceiling or a
    balance — and what actually reaches the model is the instruction plus offers that
    are public by construction, because the merchant signed and published them.
    """
    parameters = set(inspect.signature(ModelProposer.propose).parameters)
    assert parameters == {"self", "instruction", "offers"}

    model = FakeModel({"sku": "FL-A", "reason": "mais barato", "rejected": []})
    ModelProposer(model).propose("um voo pra Córdoba", CATALOG)

    instruction, candidates = model.calls[0]
    assert instruction == "um voo pra Córdoba"
    assert all(candidate in CATALOG for candidate in candidates)


# ── what the model gets to read ─────────────────────────────────────────────
def test_an_offer_line_carries_the_attributes_that_decide_between_two_fares() -> None:
    line = offer_line(
        {
            "merchant_id": "vuelaya",
            "item": {
                "sku": "FL-X", "title": "São Paulo → Córdoba", "category": "travel",
                "stops": 0, "duration_minutes": 185, "departs": "10:45",
                "checked_bag": True, "refundable": True,
            },
            "total": {"minor_units": 15200, "currency": "USD", "scale": 2},
        }
    )

    assert "152.00 USD" in line
    assert "nonstop" in line and "3h05" in line and "departs 10:45" in line
    assert "checked bag" in line and "refundable" in line


def test_an_offer_line_omits_attributes_its_category_cannot_have() -> None:
    """A hotel row reading "no checked bag" is noise on every line the model reads."""
    hotel = offer_line(
        {
            "merchant_id": "vuelaya",
            "item": {
                "sku": "HT-X", "title": "Hotel Córdoba Centro", "category": "lodging", "nights": 3,
            },
            "total": {"minor_units": 22000, "currency": "USD", "scale": 2},
        }
    )

    assert "3 nights" in hotel
    assert "bag" not in hotel and "nonstop" not in hotel


# ── the switch ──────────────────────────────────────────────────────────────
def test_a_clean_clone_proposes_by_rules_with_no_account_and_no_network(monkeypatch) -> None:
    for variable in ("AVAL_LLM_AGENT", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(variable, raising=False)

    assert isinstance(build_proposer(), RuleProposer)


def test_wanting_the_model_without_a_credential_still_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("AVAL_LLM_AGENT", "1")
    for variable in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(variable, raising=False)

    assert isinstance(build_proposer(), RuleProposer)


# ── the third answer ────────────────────────────────────────────────────────
def test_a_request_that_names_no_destination_is_asked_about_not_guessed() -> None:
    """The silent approval this closes: every word here is a stop word, so nothing
    narrows the catalogue and the cheapest fare would win by default."""
    answer = RuleProposer().propose("compre um voo", CATALOG)

    assert isinstance(answer, Question)
    assert "Where to" in answer.text


def test_a_request_naming_something_nobody_sells_is_asked_about_too() -> None:
    """Same failure, different sentence: the agent cannot tell what is wanted."""
    assert isinstance(RuleProposer().propose("compre um voo pra Marte", CATALOG), Question)


def test_a_request_that_names_a_destination_is_answered_not_questioned() -> None:
    answer = RuleProposer().propose("compre um voo pra Córdoba", CATALOG)

    assert isinstance(answer, Proposal)
    assert answer.offer["item"]["sku"] == "FL-A"


def test_the_model_may_ask_instead_of_choosing() -> None:
    answer = ModelProposer(FakeModel({"question": "Para Córdoba ou Buenos Aires?"})).propose(
        "quero viajar em setembro", CATALOG
    )

    assert answer == Question("Para Córdoba ou Buenos Aires?")


def test_an_empty_question_is_not_an_answer_and_falls_back() -> None:
    """A model that asks nothing has not asked. The rules take the wheel back."""
    answer = ModelProposer(FakeModel({"question": "   "})).propose(
        "compre um voo pra Córdoba", CATALOG
    )

    assert isinstance(answer, Proposal)

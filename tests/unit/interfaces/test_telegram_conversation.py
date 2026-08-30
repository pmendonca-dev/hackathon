from __future__ import annotations

from datetime import timedelta

import pytest

from aval.interfaces.telegram.config import MandateDefaults
from aval.interfaces.telegram.conversation import (
    Draft,
    ModelTalker,
    RuleTalker,
    Turn,
    build_talker,
)

CATEGORIES = ("lodging", "travel")

DEFAULTS = MandateDefaults(
    merchants=("vuelaya",),
    categories=("travel",),
    currency="USD",
    scale=2,
    limit_minor_units=20_000,
    ceiling_minor_units=50_000,
    valid_for=timedelta(days=30),
    max_uses=3,
    usage_window=timedelta(days=30),
)


def talk(answer, history=("quero um hotel",)) -> Draft:
    turns = tuple(Turn("user", text) for text in history)
    model = lambda *_: answer if not isinstance(answer, Exception) else _raise(answer)  # noqa: E731
    return ModelTalker(model).respond(turns, categories=CATEGORIES, defaults=DEFAULTS)


def _raise(error: Exception):
    raise error


def test_question_keeps_talking_without_a_spec():
    draft = talk({"reply": "Up to how much per night?", "mandate": None})
    assert draft.spec is None
    assert draft.reply == "Up to how much per night?"


def test_complete_answer_becomes_a_confirmable_spec():
    draft = talk(
        {
            "reply": "Hotel up to 300 dollars, for 7 days, 2 times.",
            "mandate": {
                "categories": ["lodging"],
                "max_amount": 300,
                "days": 7,
                "times": 2,
            },
        }
    )
    assert draft.spec is not None
    assert draft.spec.categories == ("lodging",)
    assert draft.spec.limit.minor_units == 30_000
    assert draft.spec.limit.currency == "USD"
    assert draft.spec.valid_for_days == 7
    assert draft.spec.max_uses == 2


@pytest.mark.parametrize(
    "answer",
    [
        # A category nobody sells, a mandate that authorizes nothing, a shape that
        # is not an answer, and the network failing. All the same failure.
        {"reply": "ok", "mandate": {"categories": ["crypto"], "max_amount": 1, "days": 1, "times": None}},
        {"reply": "ok", "mandate": {"categories": ["travel"], "max_amount": 0, "days": 7, "times": None}},
        {"reply": "ok", "mandate": {"categories": ["travel"], "max_amount": 10, "days": 0, "times": None}},
        {"reply": "", "mandate": None},
        "not an object",
        TimeoutError("model unreachable"),
    ],
)
def test_every_model_failure_falls_back_to_the_rules(answer):
    draft = talk(answer, history=("hotel até 300 por 7 dias, 2x",))
    expected = RuleTalker().respond(
        (Turn("user", "hotel até 300 por 7 dias, 2x"),),
        categories=CATEGORIES,
        defaults=DEFAULTS,
    )
    assert draft == expected
    assert draft.spec is not None and draft.spec.limit.minor_units == 30_000


def test_no_credential_means_no_model(monkeypatch):
    monkeypatch.setenv("AVAL_TELEGRAM_LLM", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(build_talker(), RuleTalker)


# ── the shopping watch ──────────────────────────────────────────────────────
"""A mandate says what may be spent. A shopping request says what to go looking for.

They arrive in the same sentence — *acompanhe um notebook até 2000 por 30 dias* — and
they are not the same thing, which is why the model answers with both or with neither.
A draft that carried a budget but no query would authorize spending with nothing to
spend it on; one that carried a query but no budget would be a search with no ceiling.
"""

SHOPPING = ("lodging", "shopping", "travel")


def shop(answer, history=("acompanhe um notebook",)) -> Draft:
    turns = tuple(Turn("user", text) for text in history)
    model = lambda *_: answer  # noqa: E731
    return ModelTalker(model).respond(turns, categories=SHOPPING, defaults=DEFAULTS)


def complete_answer(**overrides):
    base = {
        "reply": "Understood: I will watch for a laptop.",
        "mandate": {
            "categories": ["shopping"],
            "max_amount": 2000.0,
            "days": 30,
            "times": 1,
        },
        "shopping": {"query": "laptop for university", "days": 30},
    }
    base.update(overrides)
    return base


def test_a_complete_shopping_sentence_produces_a_query_and_a_deadline():
    draft = shop(complete_answer())
    assert draft.shopping is not None
    assert draft.shopping.query == "laptop for university"
    assert draft.shopping.watch_days == 30
    assert draft.shopping.max_minor_units == 200_000
    assert draft.shopping.currency == "USD"
    assert draft.shopping.category == "shopping"


def test_shopping_sentence_requires_budget_and_deadline_before_confirmation():
    """No mandate means nothing to confirm, and no watch to hang off it."""
    draft = shop({"reply": "Up to how much do you want to spend?", "mandate": None, "shopping": None})
    assert draft.spec is None
    assert draft.shopping is None


def test_a_query_without_a_mandate_authorizes_nothing():
    """The model may not hand back something to search for and no ceiling to search
    under. Half a draft is not a draft."""
    draft = shop(complete_answer(mandate=None))
    assert draft.spec is None
    assert draft.shopping is None


def test_a_mandate_without_a_query_is_still_an_ordinary_mandate():
    """Someone describing only authority gets only authority — and no watch."""
    draft = shop(complete_answer(shopping=None))
    assert draft.spec is not None
    assert draft.shopping is None


@pytest.mark.parametrize(
    "shopping",
    [
        {"query": "", "days": 30},
        {"query": "   ", "days": 30},
        {"query": "notebook", "days": 0},
        {"query": "notebook", "days": -5},
        {"query": "notebook"},
        {"days": 30},
        "not an object",
        [],
    ],
)
def test_an_unusable_search_is_dropped_rather_than_guessed(shopping):
    assert shop(complete_answer(shopping=shopping)).shopping is None


def test_the_watch_never_outlives_the_mandate_it_hangs_from():
    """A search running past the authority that pays for it would be a standing order
    against nothing. The mandate's own window is the ceiling."""
    draft = shop(complete_answer(shopping={"query": "notebook", "days": 365}))
    assert draft.shopping is not None
    assert draft.shopping.watch_days == draft.spec.valid_for_days


def test_a_long_query_cannot_become_the_search():
    draft = shop(complete_answer(shopping={"query": "x" * 5000, "days": 30}))
    assert draft.shopping is not None
    assert len(draft.shopping.query) <= 300


def test_the_rules_still_answer_when_the_model_fails():
    """The fallback has no search in it: a regex that guessed what to buy on the open
    web would be the one component here allowed to invent a purchase."""
    draft = shop(Exception("boom") and {"reply": "", "mandate": None})
    assert draft.shopping is None

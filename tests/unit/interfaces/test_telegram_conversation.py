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
    card_number="4242424242424242",
)


def talk(answer, history=("quero um hotel",)) -> Draft:
    turns = tuple(Turn("user", text) for text in history)
    model = lambda *_: answer if not isinstance(answer, Exception) else _raise(answer)  # noqa: E731
    return ModelTalker(model).respond(turns, categories=CATEGORIES, defaults=DEFAULTS)


def _raise(error: Exception):
    raise error


def test_question_keeps_talking_without_a_spec():
    draft = talk({"resposta": "Até quanto por noite?", "mandato": None})
    assert draft.spec is None
    assert draft.reply == "Até quanto por noite?"


def test_complete_answer_becomes_a_confirmable_spec():
    draft = talk(
        {
            "resposta": "Hotel até 300 dólares, por 7 dias, 2 vezes.",
            "mandato": {
                "categorias": ["lodging"],
                "valor_maximo": 300,
                "dias": 7,
                "vezes": 2,
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
        {"resposta": "ok", "mandato": {"categorias": ["crypto"], "valor_maximo": 1, "dias": 1, "vezes": None}},
        {"resposta": "ok", "mandato": {"categorias": ["travel"], "valor_maximo": 0, "dias": 7, "vezes": None}},
        {"resposta": "ok", "mandato": {"categorias": ["travel"], "valor_maximo": 10, "dias": 0, "vezes": None}},
        {"resposta": "", "mandato": None},
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

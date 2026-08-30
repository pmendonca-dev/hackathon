"""The LLM sits in the proposing half, and nowhere else.

Swapping the rule reader for a model changes what the agent *wants*. It changes nothing
about what may be bought, because the core never reads this text and never sees the
object it produces. These tests hold that line from both sides:

- whatever the model returns is coerced into the same `PurchaseIntent` the rules
  produce, and a hostile or malformed answer falls back rather than propagating;
- the model is never told the mandate's limit, ceiling or balance, so a prompt-injected
  model has nothing to leak.
"""

from __future__ import annotations

import pytest

from aval.agent.intent import PurchaseIntent, parse_intent
from aval.agent.llm_intent import LlmIntentReader, build_intent_reader


class FakeModel:
    """Stands in for the Anthropic client. Records what it was asked."""

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, instruction: str) -> object:
        self.prompts.append(instruction)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_a_model_answer_becomes_the_same_intent_shape_the_rules_produce() -> None:
    reader = LlmIntentReader(FakeModel({"category": "travel", "max_minor_units": 15000, "keywords": ["cordoba"]}))

    intent = reader.read("compre um voo para Córdoba abaixo de $150")

    assert intent == PurchaseIntent(category="travel", max_minor_units=15000, keywords=("cordoba",))


def test_a_model_timeout_falls_back_to_the_rules_instead_of_failing_the_purchase() -> None:
    """The stage version of this: no API key, a slow network, a rate limit. The demo
    must not depend on any of them."""
    reader = LlmIntentReader(FakeModel(TimeoutError("upstream slow")))

    intent = reader.read("compre um voo para Córdoba abaixo de $150")

    assert intent == parse_intent("compre um voo para Córdoba abaixo de $150")


def test_a_malformed_model_answer_falls_back_rather_than_propagating(
) -> None:
    reader = LlmIntentReader(FakeModel({"category": 42, "max_minor_units": "muito"}))

    intent = reader.read("compre um voo para Córdoba")

    assert intent == parse_intent("compre um voo para Córdoba")


def test_a_category_the_model_invented_is_not_accepted(
) -> None:
    """The model proposes from a closed set. An unknown category would not be an
    interesting attack — the core would refuse it — but it would make the agent
    unreadable, and a demo that shows nonsense proves nothing."""
    reader = LlmIntentReader(FakeModel({"category": "weapons", "max_minor_units": None, "keywords": []}))

    intent = reader.read("compre um voo")

    assert intent.category in ("travel", "lodging")


def test_a_negative_or_absurd_price_is_dropped_not_trusted() -> None:
    reader = LlmIntentReader(FakeModel({"category": "travel", "max_minor_units": -500, "keywords": []}))

    intent = reader.read("compre um voo")

    assert intent.max_minor_units is None


def test_the_model_is_never_told_the_budget_the_ceiling_or_the_balance() -> None:
    """The reader takes an instruction and nothing else. There is no parameter for
    mandate state, so a prompt-injected model has no private figure to exfiltrate —
    and the demo does not ship the buyer's budget to a third party to parse a sentence.
    """
    model = FakeModel({"category": "travel", "max_minor_units": None, "keywords": []})
    reader = LlmIntentReader(model)

    reader.read("compre um voo para Córdoba abaixo de $150")

    sent = "\n".join(model.prompts)
    for secret in ("20000", "50000", "limit", "ceiling", "orçamento", "saldo", "mandate_"):
        assert secret not in sent


def test_without_configuration_the_reader_is_the_rule_based_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No API key, no behaviour change. The rules stay the default so a clean clone
    runs the whole case with no account and no network."""
    monkeypatch.delenv("AVAL_LLM_AGENT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    reader = build_intent_reader()

    assert reader.read("compre um voo para Córdoba abaixo de $150") == parse_intent(
        "compre um voo para Córdoba abaixo de $150"
    )

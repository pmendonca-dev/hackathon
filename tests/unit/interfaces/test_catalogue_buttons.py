"""Um botão do catálogo tem de entregar o que promete.

O botão diz uma intenção — *um voo para Córdoba* — e o agente é quem escolhe a
oferta, que é exatamente o produto. O preço disso é que a tela promete um valor
("a partir de US$ 118") que só o agente pode cumprir. Este teste é o que segura
essa promessa contra o catálogo real.
"""

from __future__ import annotations

import pytest

from aval.agent.intent import parse_intent
from aval.agent.proposer import choose_offer
from aval.interfaces.telegram import views
from aval.interfaces.telegram.gateway import MoneyView, OfferView
from aval.merchant.catalog import CATALOG


def _offers() -> list[OfferView]:
    return [
        OfferView(item.sku, item.title, MoneyView(item.minor_units, item.currency, item.scale), item.category)
        for item in CATALOG
    ]


def _raw() -> list[dict]:
    return [
        {
            "item": {"sku": item.sku, "title": item.title, "category": item.category},
            "total": {
                "minor_units": item.minor_units,
                "currency": item.currency,
                "scale": item.scale,
            },
        }
        for item in CATALOG
    ]


@pytest.mark.parametrize("wish", views.wishes(_offers()), ids=lambda wish: wish.slug)
def test_every_button_delivers_the_price_it_advertises(wish: views.Wish) -> None:
    chosen = choose_offer(_raw(), parse_intent(wish.instruction))
    assert chosen is not None, f"{wish.instruction!r} matched nothing"
    assert chosen["total"]["minor_units"] == wish.cheapest.minor_units


def test_no_button_exists_for_something_the_agent_cannot_be_asked_for() -> None:
    """A button for a category `parse_intent` cannot produce is a dead button.

    Asserted against the parser rather than against today's catalogue: what the
    merchant sells is not this lane's business, but whether the agent can be asked
    for it is.
    """
    offered = {wish.category for wish in views.wishes(_offers())}
    reachable = {parse_intent(wish.instruction).category for wish in views.wishes(_offers())}
    assert offered <= reachable, f"no way to ask the agent for {offered - reachable}"
    # And the converse is expected: the catalogue sells packages nobody can ask for,
    # which is the offer the agent must never be able to reach by tapping a button.
    assert {item.category for item in CATALOG} - offered


def test_a_wish_slug_survives_a_round_trip() -> None:
    offers = _offers()
    for wish in views.wishes(offers):
        assert views.wish_for(offers, wish.slug) == wish
    assert views.wish_for(offers, "nao-existe") is None

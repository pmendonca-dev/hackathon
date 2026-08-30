"""What Computer A asks the web for, and what it is allowed to bring back.

These two types are the entire vocabulary crossing the gap between the half of the
system that can reach the open internet and the half that can move money. They are
deliberately small and deliberately inert: no signature, no terms hash, no offer id.
A `DiscoveredOffer` is a *claim about a public page*, not something a seller committed
to, and nothing downstream may treat it as one — Computer B re-issues it as a signed
offer of its own before the core is ever asked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# What marks a watch instruction as a shopping request rather than the free text the
# catalogue agent reads. A watch row stores one `instruction` column and now carries two
# kinds of thing, so the discriminator has to be in the value — and it has to be one no
# person would ever type by accident.
SHOPPING_MARKER = "aval_shopping"


@dataclass(frozen=True)
class ShoppingRequest:
    """One thing a person asked to be watched for.

    The cap travels with the request so the search can be told a ceiling, but it is a
    *preference*, not authority: the mandate's own limit is evaluated later by the core
    and neither depends on nor trusts this number.
    """

    query: str
    category: str
    max_minor_units: int
    currency: str
    scale: int = 2


@dataclass(frozen=True)
class DiscoveredOffer:
    """A public page that appears to sell the thing, normalized.

    `source_merchant` is derived from the URL's host rather than copied from the
    model's answer. Asked for real offers, `gpt-4.1-mini` named "Mercado Livre" beside
    a `gamehunter.com.br` link — showing that claim would tell a buyer they are being
    sent somewhere they are not.
    """

    title: str
    source_merchant: str
    source_url: str
    amount_minor_units: int
    currency: str
    evidence: str
    scale: int = 2


def encode_shopping_request(request: ShoppingRequest) -> str:
    """A shopping request as the one string a watch row can hold.

    `Watch.instruction` is deliberately re-read on every tick rather than frozen into
    columns, so that what the agent looks for is always what the person actually said.
    A structured request keeps that property: it is still just the instruction, only
    written in a form the discovery half can act on.
    """
    return json.dumps(
        {
            SHOPPING_MARKER: 1,
            "query": request.query,
            "category": request.category,
            "max_minor_units": request.max_minor_units,
            "currency": request.currency,
            "scale": request.scale,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def decode_shopping_request(instruction: str) -> ShoppingRequest | None:
    """The request a watch stored, or None when this watch shops the catalogue.

    Returning None rather than raising is what keeps the travel demo working untouched:
    an instruction that is not a shopping request is free text, and free text is what
    the catalogue proposer has always read.
    """
    try:
        payload: Any = json.loads(instruction)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get(SHOPPING_MARKER):
        return None
    query = payload.get("query")
    currency = payload.get("currency")
    category = payload.get("category")
    cap = payload.get("max_minor_units")
    scale = payload.get("scale", 2)
    if not isinstance(query, str) or not query.strip():
        return None
    if not isinstance(currency, str) or len(currency) != 3:
        return None
    if not isinstance(category, str) or not category.strip():
        return None
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        return None
    if isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= 18:
        return None
    return ShoppingRequest(
        query=query,
        category=category,
        max_minor_units=cap,
        currency=currency.upper(),
        scale=scale,
    )

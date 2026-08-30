"""What Computer A asks the web for, and what it is allowed to bring back.

These two types are the entire vocabulary crossing the gap between the half of the
system that can reach the open internet and the half that can move money. They are
deliberately small and deliberately inert: no signature, no terms hash, no offer id.
A `DiscoveredOffer` is a *claim about a public page*, not something a seller committed
to, and nothing downstream may treat it as one — Computer B re-issues it as a signed
offer of its own before the core is ever asked.
"""

from __future__ import annotations

from dataclasses import dataclass


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

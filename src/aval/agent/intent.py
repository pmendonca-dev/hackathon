"""Turning what a person typed into what the agent will try to buy.

This is a rule-based reader on purpose. A language model would sit exactly here — it
is the *proposing* half of the system — and swapping this module for one changes
nothing about what may be bought, because the proposal is not the decision. The core
never reads this text and never sees this object.

That separation is the point: the agent may be talked into asking for anything.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PRICE = re.compile(r"(?:R?\$|usd\s*)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+)", re.IGNORECASE)

LODGING_WORDS = ("hotel", "hospedagem", "pousada", "lodging", "diaria", "noite")

STOP_WORDS = frozenset(
    {
        "a", "abaixo", "ate", "com", "compra", "comprar", "compre", "de", "do", "da", "das",
        "dos", "e", "em", "me", "meu", "minha", "na", "no", "o", "os", "para", "por", "que",
        "quero", "reserve", "reserva", "se", "um", "uma", "usd", "valor", "voo", "flight",
        "buy", "book", "the", "to", "under", "below", "for", "me", "please",
    }
)


def fold(text: str) -> str:
    """Strip accents so `Cordoba` and `Córdoba` are the same word to match on."""
    normalised = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in normalised if unicodedata.category(char) != "Mn")


@dataclass(frozen=True)
class PurchaseIntent:
    category: str
    max_minor_units: int | None = None
    keywords: tuple[str, ...] = field(default_factory=tuple)


def _price_to_minor_units(raw: str) -> int:
    cleaned = raw.replace(".", "").replace(",", ".") if "," in raw else raw.replace(",", "")
    return int(round(float(cleaned) * 100))


def parse_intent(text: str) -> PurchaseIntent:
    folded = fold(text)
    category = "lodging" if any(word in folded for word in LODGING_WORDS) else "travel"
    prices = [_price_to_minor_units(match) for match in PRICE.findall(folded)]
    keywords = tuple(
        word
        for word in re.findall(r"[a-z]{3,}", folded)
        if word not in STOP_WORDS and not word.isdigit()
    )
    # The largest number in the sentence is the ceiling the person had in mind. A
    # smaller one usually names a date or a quantity, not a budget.
    return PurchaseIntent(
        category=category,
        max_minor_units=max(prices) if prices else None,
        keywords=keywords,
    )

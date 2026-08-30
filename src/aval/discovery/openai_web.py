"""Real offers, found on the open web, reduced to something the core can refuse.

This is the only place in AVAL that reads the public internet, and it runs on the one
computer that holds no signing key, no database and no processor credential. That is
the whole reason the split exists: the component most exposed to untrusted text is the
component that can do the least with it.

Everything arriving here is hostile until proven otherwise. The answer is written by a
language model summarising pages it just read, so a "price" may be a sentence, a "url"
may be `javascript:`, and the seller name may simply not match the link — in real runs
against `gpt-4.1-mini` it named "Mercado Livre" beside a `gamehunter.com.br` URL and
"Shopee" beside `promotech.app.br`. So the normalizer below keeps only what it can
check for itself, derives the seller from the link rather than the claim, and drops the
whole candidate at the first thing that does not hold up.

It also never raises. A watch that could not search has not found anything *yet*, and
one failing search must not end a scheduler tick that every other watch shares.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aval.discovery.models import DiscoveredOffer, ShoppingRequest

MODEL = "gpt-4.1-mini"

# Five is what a person can read in a chat message, and enough for the core to have a
# real choice. More is a wall of links nobody checks.
MAX_CANDIDATES = 5

# These strings end up in a Telegram message. A title is allowed to be a title.
MAX_TITLE = 200
MAX_EVIDENCE = 400

SYSTEM = """Você procura, na web pública, produtos à venda que atendam ao pedido.

Regras:
- Só páginas públicas de venda. Nunca acesse área logada, carrinho ou checkout.
- Devolva o preço anunciado, em números, na moeda pedida. Se a página não mostra um preço claro, não devolva a oferta.
- A URL tem que ser a página do produto, em https.
- Em "evidence", cite em uma frase curta onde o preço aparece.
- No máximo cinco ofertas. Se não achar nenhuma que sirva, devolva a lista vazia.
- Você não compra nada e não decide nada: só relata o que está publicado."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "merchant": {"type": "string"},
                    "url": {"type": "string"},
                    "price": {"type": "number"},
                    "currency": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "merchant", "url", "price", "currency", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["offers"],
    "additionalProperties": False,
}


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None


def _safe_url(value: Any) -> tuple[str, str] | None:
    """The link and the host it really points at, or nothing.

    Only `https` survives: a watch result is a link a person will tap, and the one
    thing this system can promise about it is that it was not downgraded on the way.
    Userinfo is refused outright — `https://real.store@evil.example/x` reads as the
    real store to a human and resolves to the attacker.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    if "@" in parts.netloc or parts.username or parts.password:
        return None
    host = parts.hostname.lower().removeprefix("www.")
    # The query string is dropped whole rather than filtered. Every real answer came
    # back tagged with `utm_source=openai`, and an allowlist of tracking keys is a list
    # that is always one parameter out of date.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")).rstrip("/"), host


def _minor_units(value: Any, scale: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN and friends
        return None
    minor = round(float(value) * 10**scale)
    return minor if minor > 0 else None


def normalize(raw: Any, request: ShoppingRequest) -> DiscoveredOffer | None:
    """One candidate, or None. Every check is one the normalizer can make alone."""
    if not isinstance(raw, dict):
        return None
    link = _safe_url(raw.get("url"))
    title = _text(raw.get("title"), MAX_TITLE)
    evidence = _text(raw.get("evidence"), MAX_EVIDENCE)
    currency = raw.get("currency")
    if link is None or title is None or evidence is None:
        return None
    if not isinstance(currency, str) or currency.strip().upper() != request.currency.upper():
        # A price in another currency is not a cheaper offer, it is a different number.
        return None
    minor = _minor_units(raw.get("price"), request.scale)
    if minor is None or minor > request.max_minor_units:
        return None
    url, host = link
    return DiscoveredOffer(
        title=title,
        source_merchant=host,
        source_url=url,
        amount_minor_units=minor,
        currency=request.currency.upper(),
        evidence=evidence,
        scale=request.scale,
    )


class OfferDiscovery:
    """The port. Computer B depends on this shape and never on the OpenAI client."""

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:  # pragma: no cover
        raise NotImplementedError


class OpenAIWebDiscovery(OfferDiscovery):
    """`responder` takes the request and returns the parsed answer.

    Keeping it a plain callable is what lets these tests exercise malformed answers,
    hostile URLs and a dead provider without a network.
    """

    def __init__(self, *, responder: Callable[[ShoppingRequest], Any]) -> None:
        self._responder = responder

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
        try:
            answer = self._responder(request)
        except Exception:
            # Not found yet, not broken. The watch stays open and tries next tick.
            return []
        if not isinstance(answer, dict):
            return []
        raw = answer.get("offers")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return []
        found: list[DiscoveredOffer] = []
        seen: set[str] = set()
        for entry in raw:
            offer = normalize(entry, request)
            if offer is None or offer.source_url in seen:
                continue
            seen.add(offer.source_url)
            found.append(offer)
            if len(found) == MAX_CANDIDATES:
                break
        return found


def _openai_responder(timeout_seconds: float) -> Callable[[ShoppingRequest], Any]:
    """The real call. Imported lazily so `openai` stays an optional dependency."""
    import openai

    client = openai.OpenAI(timeout=timeout_seconds, max_retries=0)

    def ask(request: ShoppingRequest) -> Any:
        cap = request.max_minor_units / 10**request.scale
        response = client.responses.create(
            model=os.environ.get("AVAL_DISCOVERY_MODEL", MODEL),
            tools=[{"type": "web_search"}],
            instructions=SYSTEM,
            # The query came from a person in a chat and is untrusted text. It travels
            # as ordinary input and can reach nothing but this one call: the answer is
            # normalized into DiscoveredOffer and nothing else.
            input=(
                f"Pedido: {request.query}\n"
                f"Moeda: {request.currency}\n"
                f"Preço máximo: {cap:.2f} {request.currency}"
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ofertas",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            },
        )
        return json.loads(response.output_text or "{}")

    return ask


def build_discovery() -> OfferDiscovery:
    """A real search only when one was deliberately turned on.

    Both switches are required, the same rule the agent and the bot already follow:
    `AVAL_DISCOVERY` says the team wants it and `OPENAI_API_KEY` says one is reachable.
    Without them discovery finds nothing, which leaves every watch open — the honest
    answer for a system that cannot look.
    """
    enabled = os.environ.get("AVAL_DISCOVERY", "").strip() not in ("", "0", "false", "False")
    if not (enabled and os.environ.get("OPENAI_API_KEY", "").strip()):
        return OpenAIWebDiscovery(responder=lambda _: {"offers": []})
    timeout = float(os.environ.get("AVAL_DISCOVERY_TIMEOUT_SECONDS", "90"))
    try:
        return OpenAIWebDiscovery(responder=_openai_responder(timeout))
    except Exception:
        return OpenAIWebDiscovery(responder=lambda _: {"offers": []})

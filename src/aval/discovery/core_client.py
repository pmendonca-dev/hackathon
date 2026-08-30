"""Computer B asking Computer A what is for sale.

The direction matters. B owns the money and the keys, so B is the one that decides when
a search happens — a watch tick, on B's own scheduler. A never pushes candidates at B
and never learns whether one was bought; it answers a question and nothing else.

Everything that comes back is untrusted. This client's whole job is to turn an HTTP
response into `DiscoveredOffer` values, or into nothing at all. It never raises: a watch
that could not reach A has not found anything *yet*, which is exactly the state a watch
already knows how to be in. Turning an unreachable edge into an exception would end a
scheduler tick that every other watch on the machine shares.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from aval.discovery.models import DiscoveredOffer, ShoppingRequest
from aval.discovery.openai_web import MAX_CANDIDATES, OfferDiscovery, normalize
from aval.security.edge_auth import EdgeSigner

DISCOVER_PATH = "/edge/v1/discover"


class CoreDiscoveryClient(OfferDiscovery):
    """The B-to-A half of the split, behind the same port the local search implements."""

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        clock: Callable[[], datetime],
        timeout_seconds: float = 120.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._signer = EdgeSigner(secret, clock=clock)
        self._timeout = timeout_seconds
        self._opener = opener or urllib.request.urlopen

    def find(self, request: ShoppingRequest) -> list[DiscoveredOffer]:
        raw = json.dumps(
            {
                "query": request.query,
                "category": request.category,
                "max_minor_units": request.max_minor_units,
                "currency": request.currency,
                "scale": request.scale,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        http = urllib.request.Request(
            f"{self._base_url}{DISCOVER_PATH}", data=raw, method="POST"
        )
        http.add_header("Content-Type", "application/json")
        http.add_header("Accept", "application/json")
        for name, value in self._signer.sign("POST", DISCOVER_PATH, raw).items():
            http.add_header(name, value)
        try:
            with self._opener(http, timeout=self._timeout) as response:
                payload = json.loads(response.read() or b"{}")
        except (urllib.error.HTTPError, OSError, ValueError):
            # Unreachable, refused, or answering nonsense: all the same to a watch.
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
            return []
        found: list[DiscoveredOffer] = []
        seen: set[str] = set()
        for entry in payload["offers"]:
            # Normalized again on this side. A's checks are A's; B does not inherit
            # them over a network hop, and the edge secret authenticates the *sender*,
            # never the content it forwarded from the open web.
            offer = _renormalize(entry, request)
            if offer is None or offer.source_url in seen:
                continue
            seen.add(offer.source_url)
            found.append(offer)
            if len(found) == MAX_CANDIDATES:
                break
        return found


def _renormalize(entry: Any, request: ShoppingRequest) -> DiscoveredOffer | None:
    """Read A's wire shape back through the same normalizer that produced it.

    A sends `amount_minor_units`; the normalizer speaks `price`. Converting here rather
    than writing a second validator is the point — one set of rules decides what a
    candidate may be, and it runs on both computers.
    """
    if not isinstance(entry, dict):
        return None
    amount = entry.get("amount_minor_units")
    if isinstance(amount, bool) or not isinstance(amount, int):
        return None
    return normalize(
        {
            "title": entry.get("title"),
            "merchant": entry.get("source_merchant"),
            "url": entry.get("source_url"),
            "price": amount / 10**request.scale,
            "currency": entry.get("currency"),
            "evidence": entry.get("evidence"),
        },
        request,
    )

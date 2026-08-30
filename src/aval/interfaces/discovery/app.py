"""Computer A's private discovery endpoint.

This is the smallest surface in the system, and it is small on purpose. A is the
computer that holds the Telegram token and the OpenAI key and reaches the open web; it
holds no signing key, no database and no processor credential. So the only thing it can
offer Computer B is an answer about what is for sale, and the only thing B can ask it
for is a search.

Nothing here imports `aval.runtime`, the core, or the Stripe adapter. That is not
tidiness — it is the boundary itself. A process that cannot import the settlement
adapter cannot be talked into settling, whatever arrives in a request body.

The HMAC is checked against the raw bytes *before* anything parses them, so a body that
fails the signature is never handed to a JSON decoder.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from aval.discovery.models import ShoppingRequest
from aval.discovery.openai_web import OfferDiscovery, build_discovery
from aval.security.edge_auth import EdgeAuthError, verify_edge_request

DISCOVER_PATH = "/edge/v1/discover"

# A query is a phrase a person typed in a chat. Longer than this is not a search.
MAX_QUERY = 300


def _bad(status: int, code: str) -> JSONResponse:
    """Errors say what failed and nothing else.

    An unauthenticated caller learns only that it was refused — never whether the
    secret was wrong, the timestamp stale, or the route real.
    """
    return JSONResponse(status_code=status, content={"error": code})


def _shopping_request(payload: object) -> ShoppingRequest | None:
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    currency = payload.get("currency")
    category = payload.get("category")
    cap = payload.get("max_minor_units")
    scale = payload.get("scale", 2)
    if not isinstance(query, str) or not query.strip():
        return None
    if not isinstance(currency, str) or len(currency.strip()) != 3:
        return None
    if not isinstance(category, str) or not category.strip():
        return None
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        return None
    if isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= 18:
        return None
    return ShoppingRequest(
        query=" ".join(query.split())[:MAX_QUERY],
        category=category.strip(),
        max_minor_units=cap,
        currency=currency.strip().upper(),
        scale=scale,
    )


def create_discovery_app(
    *,
    secret: str,
    discovery: OfferDiscovery | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> FastAPI:
    """The whole of Computer A's inbound surface: one route, plus liveness."""
    finder = discovery or build_discovery()
    clock = now_provider or (lambda: datetime.now(UTC))
    app = FastAPI(title="AVAL discovery edge", docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        """Unauthenticated and deliberately empty: a launcher needs to know the process
        answers, and nobody needs to learn anything else from it."""
        return {"status": "ok"}

    @router.post(DISCOVER_PATH)
    async def discover(request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            verify_edge_request(secret, "POST", DISCOVER_PATH, raw, request.headers, clock())
        except EdgeAuthError:
            return _bad(401, "edge_unauthenticated")
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return _bad(400, "edge_payload_malformed")
        shopping = _shopping_request(payload)
        if shopping is None:
            return _bad(422, "edge_request_invalid")
        offers = finder.find(shopping)
        return JSONResponse(
            content={
                "offers": [
                    {
                        "title": offer.title,
                        "source_merchant": offer.source_merchant,
                        "source_url": offer.source_url,
                        "amount_minor_units": offer.amount_minor_units,
                        "currency": offer.currency,
                        "scale": offer.scale,
                        "evidence": offer.evidence,
                    }
                    for offer in offers
                ]
            }
        )

    app.include_router(router)
    return app

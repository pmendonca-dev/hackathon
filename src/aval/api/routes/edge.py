"""Computer B's private outbox, read by Computer A and nobody else.

Two routes, both fail-closed: without `AVAL_EDGE_TO_CORE_SECRET` the router is not
mounted at all, so on a single-machine deployment these paths are a genuine 404 rather
than an endpoint waiting to be found. That is the same shape the destructive demo
routers already use, and for the same reason — a surface that exists only when someone
turned it on cannot be reached by someone who did not.

The HMAC is checked against the raw request line before anything else happens. It
authenticates the *sender*, not the content: it says the process on the other computer
asked, and nothing more. Neither route can move money, change a mandate or create a
watch — the worst a stolen credential does is read what the outbox holds and mark it
delivered, which is why the payload is filtered on the way in rather than here.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.infrastructure.sqlite.edge_event_repository import SqliteEdgeEventRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.security.edge_auth import EdgeAuthError, verify_edge_request

EVENTS_PATH = "/edge/v1/events"

# One poll is a batch, not the whole history. A chat that was offline for a day should
# come back with the news, not with a thousand messages at once.
PAGE_SIZE = 50


def edge_to_core_secret() -> str:
    """The credential A signs with. Empty means the split was never turned on."""
    return os.environ.get("AVAL_EDGE_TO_CORE_SECRET", "").strip()


async def _require_edge(request: Request, secret: str, method: str, path: str) -> None:
    raw = await request.body()
    try:
        verify_edge_request(secret, method, path, raw, request.headers, _now(request))
    except EdgeAuthError as error:
        # Says it was refused and never why. A caller learns nothing about the secret,
        # the clock, or whether the route it guessed exists.
        raise ApiError(401, "edge_unauthenticated", "Não autenticado.") from error


def _now(request: Request) -> datetime:
    """Wall clock, and deliberately **not** `runtime.clock`.

    Every validity decision in this system reads the demo clock, because an operator
    advancing it is how a judge watches a mandate expire. This one must not: the demo
    offset exists only on B, and A signs against the real time on its own machine. Using
    the offset clock here would mean that advancing the demo — a legitimate, expected
    action — silently severs the link between the two computers and every result stops
    being delivered.

    Nothing about authority is decided here, so nothing is lost by ignoring the offset.
    """
    return datetime.now(UTC)


def create_edge_router(secret: str) -> APIRouter:
    router = APIRouter(tags=["edge"], include_in_schema=False)

    @router.get(EVENTS_PATH)
    async def read_events(request: Request, after: int | None = Query(default=None)) -> dict[str, Any]:
        """What A has not confirmed yet. Reading is not delivering."""
        await _require_edge(request, secret, "GET", _signed_path(request))
        runtime = runtime_of(request)
        with runtime.engine.connect() as connection:
            events = SqliteEdgeEventRepository(connection).undelivered_after(
                after=after, limit=PAGE_SIZE
            )
        return {"events": [event.as_dict() for event in events]}

    @router.post(EVENTS_PATH + "/{event_id}/ack", status_code=204)
    async def acknowledge(request: Request, event_id: int) -> Response:
        """A says Telegram took it. Idempotent: an id already delivered, or one that
        never existed, both answer 204 — a retry after a lost response must be free,
        because the alternative is A choosing between telling someone twice and never
        telling them at all."""
        await _require_edge(request, secret, "POST", _signed_path(request))
        runtime = runtime_of(request)
        delivered_at = runtime.clock.now()
        run_in_write_transaction(
            runtime.engine,
            lambda connection: SqliteEdgeEventRepository(connection).mark_delivered(
                event_id, delivered_at=delivered_at
            ),
        )
        return Response(status_code=204)

    return router


def _signed_path(request: Request) -> str:
    """The path exactly as the caller signed it, query string included.

    `after=` changes what comes back, so it has to be inside the signature. Signing the
    bare path would let anything on the wire rewrite the cursor and make A skip an event
    it never saw — a purchase silently never reported.
    """
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path

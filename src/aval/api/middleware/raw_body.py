from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RawBodyMiddleware(BaseHTTPMiddleware):
    """Captures the incoming body before downstream JSON parsing can transform it."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.raw_body = await request.body()
        return await call_next(request)


def raw_body_from(request: Request) -> bytes:
    try:
        return request.state.raw_body
    except AttributeError as error:
        raise RuntimeError("raw body middleware is required for this route") from error

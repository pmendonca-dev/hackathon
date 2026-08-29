from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse

from aval.api.middleware.raw_body import RawBodyMiddleware, raw_body_from


def test_raw_body_middleware_preserves_original_bytes_before_json_parsing() -> None:
    """Catches a middleware that reconstructs bytes from a parsed JSON object."""
    async def inspect(request: Request) -> JSONResponse:
        parsed = await request.json()
        return JSONResponse({"raw": raw_body_from(request).decode("utf-8"), "parsed": parsed})

    body = b'{"z":"Caf\xc3\xa9","a":1}'
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {"type": "http", "method": "POST", "path": "/inspect", "headers": [(b"content-type", b"application/json")]},
        receive,
    )
    response = asyncio.run(RawBodyMiddleware(object()).dispatch(request, inspect))

    assert response.status_code == 200
    assert response.body == b'{"raw":"{\\"z\\":\\"Caf\xc3\xa9\\",\\"a\\":1}","parsed":{"z":"Caf\xc3\xa9","a":1}}'

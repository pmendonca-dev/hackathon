from __future__ import annotations

from fastapi import HTTPException, Request

from aval.adapters.ucp.http_signatures import Rfc9421Verifier, SignedRequest
from aval.api.middleware.raw_body import raw_body_from
from aval.domain.entities import AgentIdentity


def authenticate_rfc9421(request: Request, verifier: Rfc9421Verifier | None) -> AgentIdentity | None:
    """Authenticate the exact received request bytes at an operational boundary."""
    if verifier is None:
        return None
    try:
        return verifier.verify(SignedRequest(
            method=request.method, authority=request.url.netloc, path=request.url.path,
            headers=dict(request.headers), body=raw_body_from(request),
        ))
    except ValueError as error:
        code = str(error)
        status = 403 if code in {"profile_not_trusted", "key_not_found"} else 422
        raise HTTPException(status_code=status, detail={"code": code}) from error

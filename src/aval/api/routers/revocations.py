"""Signed revocation over the protocol boundary.

The same act the authorization edge exposes at `POST /mandates/{id}/revocation`, offered
here in the shape the protocol lane and the Telegram gateway speak: plural, RFC 9421
authenticated, and answered with `202` because the revocation is recorded the moment it
verifies and every later decision reads it.

Authentication answers *who is asking*; the signed JWS answers *who may revoke*. Both
are required, and neither substitutes for the other: an authenticated agent cannot
revoke a mandate it does not hold the key for, and a valid revocation token does not
open the door to an unauthenticated caller.
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.authentication import authenticate_rfc9421
from aval.application.authorization_core import AuthorizationCore

# The core raises ValueError with these sentences; the protocol answers with codes.
REVOCATION_CODES = {
    "malformed revocation JWS": (422, "revocation_malformed"),
    "malformed compact JWS": (422, "revocation_malformed"),
    "unsupported compact JWS": (422, "revocation_malformed"),
    "invalid compact JWS signature": (403, "revocation_signature_invalid"),
    "revocation mandate does not match authority": (403, "revocation_mandate_mismatch"),
    "invalid revocation scope": (422, "revocation_scope_invalid"),
    "revocation scope is not allowed": (403, "revocation_scope_not_allowed"),
    "guardian and issuer may only revoke the mandate": (403, "revocation_scope_not_allowed"),
    "revocation payload is incomplete": (422, "revocation_payload_incomplete"),
    "unknown revocation authority": (403, "revocation_authority_unknown"),
}


class RevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signed_revocation: str = Field(min_length=1)


def _named_mandate(token: str) -> str | None:
    """Which mandate the token says it is about.

    Read without verifying, and only ever used to *refuse*. The core has already checked
    the signature against the authorities of the mandate this names, so nothing is
    granted on the strength of these bytes — they just answer whether the caller aimed
    the token at the mandate in the URL.
    """
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError):
        return None
    named = claims.get("mandate_id") if isinstance(claims, dict) else None
    return None if named is None else str(named)


def create_revocation_router(
    core: AuthorizationCore, *, verifier: Rfc9421Verifier | None = None
) -> APIRouter:
    router = APIRouter()

    def require_agent(request: Request) -> None:
        authenticate_rfc9421(request, verifier)

    @router.post(
        "/mandates/{mandate_id}/revocations",
        status_code=202,
        dependencies=[Depends(require_agent)],
    )
    async def revoke(mandate_id: str, body: RevocationInput) -> dict[str, str]:
        if core.mandate(mandate_id) is None:
            raise HTTPException(404, detail={"code": "mandate_not_found"})
        try:
            core.submit_signed_revocation(body.signed_revocation)
        except ValueError as error:
            status, code = REVOCATION_CODES.get(str(error), (403, "revocation_invalid"))
            raise HTTPException(status, detail={"code": code}) from error
        # A token is authority over the mandate it names, never over the one in the URL.
        # If the two disagree the named mandate was revoked and this one was not, so the
        # caller must be told rather than handed a success for something else.
        #
        # Read the *token*, not the mandate status: a scoped revocation — a cancelled
        # card, a frozen budget — deliberately leaves the mandate ACTIVE. Judging by
        # status called every one of those a mismatch and answered 403 for a revocation
        # that had already been applied and committed, which is the worst of both: the
        # caller retries something that already happened.
        named = _named_mandate(body.signed_revocation)
        if named is not None and named != mandate_id:
            raise HTTPException(403, detail={"code": "revocation_mandate_mismatch"})
        mandate = core.mandate(mandate_id)
        revoked = mandate is not None and mandate.status.value == "REVOKED"
        return {"mandate_id": mandate_id, "status": "revoked" if revoked else "scope_revoked"}

    return router

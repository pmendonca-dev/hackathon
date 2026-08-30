from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.authentication import authenticate_rfc9421
from aval.application.authorization_core import AuthorizationCore


class SignedRevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signed_revocation: str


def create_revocation_router(
    core: AuthorizationCore, *, verifier: Rfc9421Verifier | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_authenticated_authority(request: Request):
        return authenticate_rfc9421(request, verifier)

    @router.post(
        "/mandates/{mandate_id}/revocations", status_code=202,
    )
    async def revoke(
        mandate_id: str,
        request: SignedRevocationInput,
        identity=Depends(require_authenticated_authority),
        idempotency_key: str = Header(alias="Idempotency-Key"),
        response: Response = None,
    ) -> dict[str, str]:
        if not idempotency_key.strip():
            raise HTTPException(400, detail={"code": "idempotency_key_required"})
        authenticated_kid = None if identity is None else identity.public_jwk.get("kid")
        result = core.submit_signed_revocation_idempotent(
            mandate_id=mandate_id,
            token=request.signed_revocation,
            idempotency_key=idempotency_key,
            authenticated_kid=authenticated_kid,
        )
        if result.replayed and response is not None:
            response.headers["Idempotent-Replayed"] = "true"
        if result.reason_code is not None:
            status = 503 if result.reason_code == "idempotency_unavailable" else 409 if result.reason_code == "idempotency_in_flight" else 422
            raise HTTPException(status, detail={"code": result.reason_code})
        assert result.mandate_id is not None
        return {"mandate_id": result.mandate_id, "status": "revoked"}

    return router

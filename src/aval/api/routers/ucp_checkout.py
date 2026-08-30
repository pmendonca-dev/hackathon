from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Request, Response

from aval.adapters.ucp.http_signatures import Rfc9421Verifier, SignedRequest
from aval.adapters.ucp.checkout_projection import project_ucp_checkout
from aval.api.middleware.raw_body import raw_body_from
from aval.application.services.checkout import DEFAULT_CHECKOUT_CATEGORY, CheckoutCommand, CheckoutService
from aval.domain.money import Money


def _error(error: ValueError) -> HTTPException:
    code = str(error)
    status = (
        503 if code == "idempotency_unavailable"
        else 409 if code == "idempotency_in_flight"
        else 403 if code in {"profile_not_trusted", "key_not_found"}
        else 422
    )
    return HTTPException(status_code=status, detail={"code": code})


def create_ucp_checkout_router(
    service: CheckoutService, *, verifier: Rfc9421Verifier | None = None
) -> APIRouter:
    """Build a router; composition injects the authenticated, raw-body protected service boundary."""
    router = APIRouter(prefix="/checkout-sessions")

    def authenticate(request: Request) -> None:
        if verifier is None:
            return
        try:
            verifier.verify(
                SignedRequest(
                    method=request.method,
                    authority=request.url.netloc,
                    path=request.url.path,
                    headers=dict(request.headers),
                    body=raw_body_from(request),
                )
            )
        except ValueError as error:
            raise _error(error) from error

    @router.post("", status_code=201)
    async def create_checkout(request: Request) -> Mapping[str, object]:
        authenticate(request)
        body = await request.json()
        try:
            total = body["total"]
            session = service.create(
                CheckoutCommand(
                    id=body["id"],
                    mandate_id=body["mandate_id"],
                    merchant_id=body["merchant_id"],
                    total=Money(total["amount"], total["currency"], total["scale"]),
                    line_items=tuple(body["line_items"]),
                    category=str(body.get("category", DEFAULT_CHECKOUT_CATEGORY)),
                    negotiated_capabilities=frozenset(body.get("capabilities", [])),
                )
            )
            return project_ucp_checkout(session)
        except (KeyError, TypeError, ValueError) as error:
            raise _error(error) from error

    @router.post("/{checkout_id}/complete")
    async def complete_checkout(checkout_id: str, request: Request, response: Response):
        authenticate(request)
        body = await request.json()
        try:
            result = service.complete(
                checkout_id,
                checkout_mandate=body.get("ap2", {}).get("checkout_mandate"),
                audience=body["audience"],
                nonce=body["nonce"],
                idempotency_key=request.headers["idempotency-key"],
            )
            if result.replayed:
                response.headers["Idempotent-Replayed"] = "true"
            return {"checkout_id": result.checkout_id, "status": result.status}
        except (KeyError, TypeError, ValueError) as error:
            raise _error(error) from error

    return router

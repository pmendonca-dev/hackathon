from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Request

from aval.adapters.ucp.checkout_projection import project_ucp_checkout
from aval.application.services.checkout import CheckoutCommand, CheckoutService
from aval.domain.money import Money


def _error(error: ValueError) -> HTTPException:
    code = str(error)
    status = 403 if code in {"profile_not_trusted", "key_not_found"} else 422
    return HTTPException(status_code=status, detail={"code": code})


def create_ucp_checkout_router(service: CheckoutService) -> APIRouter:
    """Build a router; composition injects the authenticated, raw-body protected service boundary."""
    router = APIRouter(prefix="/checkout-sessions")

    @router.post("", status_code=201)
    async def create_checkout(request: Request) -> Mapping[str, object]:
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
                    negotiated_capabilities=frozenset(body.get("capabilities", [])),
                )
            )
            return project_ucp_checkout(session)
        except (KeyError, TypeError, ValueError) as error:
            raise _error(error) from error

    @router.post("/{checkout_id}/complete")
    async def complete_checkout(checkout_id: str, request: Request):
        body = await request.json()
        try:
            return service.complete(
                checkout_id,
                checkout_mandate=body.get("ap2", {}).get("checkout_mandate"),
                audience=body["audience"],
                nonce=body["nonce"],
                idempotency_key=request.headers["idempotency-key"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _error(error) from error

    return router

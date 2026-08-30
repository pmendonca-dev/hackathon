from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from aval.adapters.acp.delegate_payment import serialize_delegated_payment
from aval.application.services.delegation import DurableDelegationService
from aval.application.services.vault import DelegationRejected, VaultService
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.authentication import authenticate_rfc9421


class CardCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_number: str


class DelegatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate_id: str
    checkout_session_id: str
    merchant_id: str
    payment_method: CardCredentialInput


class AllowanceResponse(BaseModel):
    reason: str
    max_amount: int
    currency: str
    checkout_session_id: str
    merchant_id: str
    expires_at: datetime


class DelegatePaymentResponse(BaseModel):
    token: str
    allowance: AllowanceResponse


def create_delegate_payment_router(
    service: VaultService | DurableDelegationService, *, verifier: Rfc9421Verifier | None = None
) -> APIRouter:
    router = APIRouter()

    def require_agent(request: Request) -> None:
        authenticate_rfc9421(request, verifier)

    @router.post(
        "/agentic_commerce/delegate_payment",
        response_model=DelegatePaymentResponse, status_code=201, dependencies=[Depends(require_agent)],
    )
    async def delegate_payment(
        request: DelegatePaymentRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        response: Response = None,
    ) -> DelegatePaymentResponse:
        if not idempotency_key.strip():
            raise HTTPException(status_code=400, detail={"code": "idempotency_key_required"})
        try:
            if isinstance(service, DurableDelegationService):
                outcome = service.delegate(
                    mandate_id=request.mandate_id, checkout_id=request.checkout_session_id,
                    merchant_id=request.merchant_id, card_number=request.payment_method.card_number,
                    idempotency_key=idempotency_key,
                )
                if outcome.replayed and response is not None:
                    response.headers["Idempotent-Replayed"] = "true"
                if outcome.payment is None:
                    status = 409 if outcome.reason_code == "idempotency_in_flight" else 422 if outcome.reason_code == "idempotency_key_reused" else 403
                    raise HTTPException(status_code=status, detail={"code": outcome.reason_code})
                delegated = outcome.payment
            else:
                delegated = service.delegate(
                    mandate_id=request.mandate_id, checkout_id=request.checkout_session_id,
                    merchant_id=request.merchant_id, card_number=request.payment_method.card_number,
                )
        except DelegationRejected as error:
            detail: object = {"code": error.reason_code} if isinstance(service, DurableDelegationService) else error.reason_code
            raise HTTPException(status_code=403, detail=detail) from error
        return DelegatePaymentResponse.model_validate(serialize_delegated_payment(delegated))

    return router

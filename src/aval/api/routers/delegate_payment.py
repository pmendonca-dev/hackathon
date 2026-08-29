from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from aval.adapters.acp.delegate_payment import serialize_delegated_payment
from aval.application.services.vault import DelegationRejected, VaultService


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


def create_delegate_payment_router(service: VaultService) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/agentic_commerce/delegate_payment",
        response_model=DelegatePaymentResponse,
    )
    async def delegate_payment(
        request: DelegatePaymentRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> DelegatePaymentResponse:
        if not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="idempotency_key_required")
        try:
            delegated = service.delegate(
                mandate_id=request.mandate_id,
                checkout_id=request.checkout_session_id,
                merchant_id=request.merchant_id,
                card_number=request.payment_method.card_number,
            )
        except DelegationRejected as error:
            raise HTTPException(status_code=403, detail=error.reason_code) from error
        return DelegatePaymentResponse.model_validate(serialize_delegated_payment(delegated))

    return router

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from aval.application.services.payment_runtime import PaymentCaptureRequest, PaymentRuntime
from aval.domain.money import Money


class AmountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int
    currency: str
    scale: int


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mandate_id: str
    checkout_session_id: str
    merchant_id: str
    token: str
    amount: AmountInput


def create_payment_capture_router(service: PaymentRuntime) -> APIRouter:
    router = APIRouter()

    @router.post("/payment-captures", status_code=201)
    async def capture(
        request: CaptureInput, idempotency_key: str = Header(alias="Idempotency-Key")
    ) -> dict[str, object]:
        if not idempotency_key.strip():
            raise HTTPException(400, detail={"code": "idempotency_key_required"})
        result = service.capture(PaymentCaptureRequest(
            mandate_id=request.mandate_id, checkout_id=request.checkout_session_id,
            merchant_id=request.merchant_id, token=request.token,
            amount=Money(request.amount.amount, request.amount.currency, request.amount.scale),
            idempotency_key=idempotency_key,
        ))
        if not result.approved or result.reservation is None:
            status = 409 if result.reason_code == "idempotency_in_flight" else 422 if result.reason_code.startswith("vault_token") else 403
            raise HTTPException(status, detail={"code": result.reason_code})
        return {
            "capture_id": result.reservation.id, "reservation_id": result.reservation.id,
            "status": "settled", "settlement_reference": result.settlement_reference,
            "receipt_url": f"/payment-captures/{result.reservation.id}/receipts",
        }

    @router.get("/payment-captures/{capture_id}/receipts")
    async def receipts(capture_id: str) -> dict[str, object]:
        capture = service.receipts_for(capture_id)
        if capture is None:
            raise HTTPException(404, detail={"code": "capture_not_found"})
        return {
            "capture_id": capture.id, "checkout_receipt": capture.checkout_receipt,
            "payment_receipt": capture.payment_receipt,
        }

    @router.get("/payment-captures/{capture_id}")
    async def capture_status(capture_id: str) -> dict[str, object]:
        capture = service.receipts_for(capture_id)
        if capture is None:
            raise HTTPException(404, detail={"code": "capture_not_found"})
        return {
            "capture_id": capture.id, "reservation_id": capture.id,
            "status": "settled", "settlement_reference": capture.settlement_reference,
        }

    return router

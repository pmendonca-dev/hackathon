from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from aval.application.services.payment_runtime import PaymentCaptureRequest, PaymentRuntime
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.authentication import authenticate_rfc9421


class CaptureAp2Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkout_mandate: str | None = None


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkout_session_id: str
    token: str
    audience: str
    nonce: str
    ap2: CaptureAp2Input = CaptureAp2Input()


def create_payment_capture_router(
    service: PaymentRuntime, *, verifier: Rfc9421Verifier | None = None
) -> APIRouter:
    router = APIRouter()

    def require_agent(request: Request) -> None:
        authenticate_rfc9421(request, verifier)

    @router.post("/payment-captures", status_code=201, dependencies=[Depends(require_agent)])
    async def capture(
        request: CaptureInput, idempotency_key: str = Header(alias="Idempotency-Key")
    ) -> dict[str, object]:
        if not idempotency_key.strip():
            raise HTTPException(400, detail={"code": "idempotency_key_required"})
        result = service.capture(PaymentCaptureRequest(
            checkout_id=request.checkout_session_id, token=request.token,
            audience=request.audience, nonce=request.nonce,
            checkout_mandate=request.ap2.checkout_mandate,
            idempotency_key=idempotency_key,
        ))
        if not result.approved or result.reservation is None:
            status = 409 if result.reason_code == "idempotency_in_flight" else 422 if result.reason_code.startswith(("vault_token", "mandate_", "merchant_authorization")) else 403
            raise HTTPException(status, detail={"code": result.reason_code})
        return {
            "capture_id": result.reservation.id, "reservation_id": result.reservation.id,
            "status": "settled", "settlement_reference": result.settlement_reference,
            "receipt_url": f"/payment-captures/{result.reservation.id}/receipts",
        }

    @router.get("/payment-captures/{capture_id}/receipts")
    async def receipts(capture_id: str, request: Request) -> dict[str, object]:
        identity = authenticate_rfc9421(request, verifier)
        if identity is None or not service.can_read_capture(identity_id=identity.id, capture_id=capture_id):
            raise HTTPException(403, detail={"code": "reader_not_authorized"})
        capture = service.receipts_for(capture_id)
        if capture is None:
            raise HTTPException(404, detail={"code": "capture_not_found"})
        return {
            "capture_id": capture.id, "checkout_receipt": capture.checkout_receipt,
            "payment_receipt": capture.payment_receipt,
        }

    @router.get("/payment-captures/{capture_id}")
    async def capture_status(capture_id: str, request: Request) -> dict[str, object]:
        identity = authenticate_rfc9421(request, verifier)
        if identity is None or not service.can_read_capture(identity_id=identity.id, capture_id=capture_id):
            raise HTTPException(403, detail={"code": "reader_not_authorized"})
        capture = service.receipts_for(capture_id)
        if capture is None:
            raise HTTPException(404, detail={"code": "capture_not_found"})
        return {
            "capture_id": capture.id, "reservation_id": capture.id,
            "status": "settled", "settlement_reference": capture.settlement_reference,
        }

    return router

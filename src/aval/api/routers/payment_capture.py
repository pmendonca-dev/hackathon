from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
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


# A refusal carries its own kind. Malformed evidence is the caller's mistake (422);
# authority withheld is a refusal (403); a store that cannot answer is fail-closed and
# temporary (503), because "unknown" must never be reported as "allowed".
UNAVAILABLE_REASONS = frozenset({"revocation_unavailable", "idempotency_unavailable"})
FORBIDDEN_REASONS = frozenset(
    {
        "mandate_revoked",
        "mandate_expired",
        "mandate_not_found",
        "mandate_ceiling",
        "merchant_out_of_scope",
        "category_not_allowed",
        "budget_exceeded",
        "budget_revoked",
        "instrument_revoked",
        "settlement_declined",
    }
)


# The core says `transaction_already_captured`; this protocol calls the same fact an
# already-spent authorization. Translating here keeps each vocabulary intact.
PROTOCOL_REASONS = {"transaction_already_captured": "authorization_proof_replayed"}


def _status_for(reason_code: str) -> int:
    if reason_code in UNAVAILABLE_REASONS:
        return 503
    if reason_code == "idempotency_in_flight":
        return 409
    if reason_code in FORBIDDEN_REASONS:
        return 403
    if reason_code.startswith(("vault_token", "mandate_", "merchant_authorization", "checkout_", "authorization_proof")):
        return 422
    return 403


def create_payment_capture_router(
    service: PaymentRuntime, *, verifier: Rfc9421Verifier | None = None
) -> APIRouter:
    router = APIRouter()

    def require_agent(request: Request) -> None:
        authenticate_rfc9421(request, verifier)

    @router.post("/payment-captures", status_code=201, dependencies=[Depends(require_agent)])
    async def capture(
        response: Response,
        request: CaptureInput,
        idempotency_key: str = Header(alias="Idempotency-Key"),
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
            reason = PROTOCOL_REASONS.get(result.reason_code, result.reason_code)
            raise HTTPException(_status_for(reason), detail={"code": reason})
        if result.replayed:
            # Same key, same body: the caller is told this is the original answer rather
            # than a second settlement, which is the difference that matters to them.
            response.headers["Idempotent-Replayed"] = "true"
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

"""Decide and capture.

Both routes are translation only. They shape a command, hand it to the core and relay
what came back — including `awaiting_human`, which is an outcome, not a failure.

Both require a signed agent request. Authentication happens at the edge, in the
dependency; authority happens in the core. Neither substitutes for the other.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from aval.api.agent_auth import require_signed_agent
from aval.api.dependencies import runtime_of
from aval.api.purchase_flow import authorize_purchase, capture_purchase
from aval.api.schemas import (
    AuthorizationResponse,
    CaptureRequest,
    CaptureResponse,
    PurchaseRequest,
)
from aval.domain.entities import AgentIdentity

router = APIRouter(tags=["authorization"])


@router.post("/authorize", response_model=AuthorizationResponse)
def authorize(
    request: Request,
    body: PurchaseRequest,
    agent: AgentIdentity = Depends(require_signed_agent),
) -> AuthorizationResponse:
    result = authorize_purchase(runtime_of(request), agent=agent, body=body)
    return AuthorizationResponse(
        decision=result.decision.value,
        reason_code=result.reason_code,
        human_summary=result.human_summary,
        escalation_id=result.escalation_id,
    )


@router.post("/capture", response_model=CaptureResponse)
def capture(
    request: Request,
    body: CaptureRequest,
    agent: AgentIdentity = Depends(require_signed_agent),
) -> CaptureResponse:
    result = capture_purchase(runtime_of(request), agent=agent, body=body)
    return CaptureResponse(
        approved=result.approved,
        reason_code=result.reason_code,
        settlement_reference=result.settlement_reference,
        reservation_id=None if result.reservation is None else result.reservation.id,
        escalation_id=result.escalation_id,
        authorization_proof=result.authorization_proof,
    )

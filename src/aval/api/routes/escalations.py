"""The way back from `awaiting_human`.

The case asks for purchases outside the mandate to be *rejected or escalated to human
approval* — never silently approved. Escalating without a return path answers only
half of that, so this is where the person answers and the purchase resumes.

The decision arrives signed. That signature is what a later "I never authorized this"
runs into.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.application.authorization_core import ApprovalError
from aval.domain.entities import Escalation

router = APIRouter(tags=["escalations"])


class EscalationDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    approval_jws: str = Field(min_length=1)


def escalation_view(escalation: Escalation) -> dict[str, Any]:
    return {
        "id": escalation.id,
        "mandate_id": escalation.mandate_id,
        "checkout_id": escalation.checkout_id,
        "merchant_id": escalation.merchant_id,
        "category": escalation.category,
        "amount": {
            "minor_units": escalation.amount.minor_units,
            "currency": escalation.amount.currency,
            "scale": escalation.amount.scale,
        },
        "reason_code": escalation.reason_code,
        "status": escalation.status.value,
        "agent_id": escalation.agent_id,
        "created_at": escalation.created_at.isoformat(),
        "expires_at": escalation.expires_at.isoformat(),
        "decided_at": None if escalation.decided_at is None else escalation.decided_at.isoformat(),
    }


@router.get("/escalations")
def list_escalations(
    request: Request, mandate_id: str | None = None, principal_id: str | None = None
) -> dict[str, Any]:
    """What is waiting on a person, by mandate or across every mandate they hold.

    One of the two scopes is required. An unscoped listing would be a feed of what
    everybody is about to buy — amount, merchant and item — to anyone who asks, so
    there is no such call. `principal_id` is what the bot and the browser use to poll
    for new approvals without knowing a mandate id in advance.
    """
    core = runtime_of(request).core
    if mandate_id is None and principal_id is None:
        raise ApiError(
            422,
            "escalation_scope_required",
            "Informe mandate_id ou principal_id; não existe listagem global.",
        )
    if mandate_id is not None:
        if core.mandate(mandate_id) is None:
            raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
        escalations = core.open_escalations(mandate_id)
    else:
        assert principal_id is not None
        escalations = core.open_escalations_for_principal(principal_id)
    return {
        "mandate_id": mandate_id,
        "principal_id": principal_id,
        "escalations": [escalation_view(item) for item in escalations],
    }


@router.get("/escalations/{escalation_id}")
def read_escalation(request: Request, escalation_id: str) -> dict[str, Any]:
    escalation = runtime_of(request).core.escalation(escalation_id)
    if escalation is None:
        raise ApiError(404, "escalation_not_found", "Escalação não encontrada.")
    return escalation_view(escalation)


@router.post("/escalations/{escalation_id}/decision")
def decide_escalation(
    request: Request, escalation_id: str, body: EscalationDecisionRequest
) -> dict[str, Any]:
    try:
        escalation, capture = runtime_of(request).core.decide_escalation(
            escalation_id=escalation_id,
            decision=body.decision,
            approval_jws=body.approval_jws,
        )
    except ApprovalError as error:
        raise ApiError(error.status_code, error.reason_code, error.human_summary) from error
    return {
        "resumed": capture is not None,
        "escalation": escalation_view(escalation),
        "capture": None
        if capture is None
        else {
            "approved": capture.approved,
            "reason_code": capture.reason_code,
            "settlement_reference": capture.settlement_reference,
            "reservation_id": None if capture.reservation is None else capture.reservation.id,
        },
    }

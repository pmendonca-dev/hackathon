"""The agent, driven from outside.

This is the surface a chat bot or an operator console points at: free text in, a real
purchase attempt out. It is intentionally the weakest-authenticated route in the
system and that is safe, because everything it can ask for still has to survive the
mandate. Talking the agent into wanting something is not the same as being allowed it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from aval.agent.purchasing_agent import PurchasingAgent
from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError

router = APIRouter(tags=["agent"])


class AgentPurchaseRequest(BaseModel):
    mandate_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


@router.get("/agent/profile")
def agent_profile(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    identity = runtime.core.agent_for_kid(runtime.agent_kid)
    if identity is None:
        raise ApiError(404, "key_not_found", "Agente de demonstração não registrado.")
    return {
        "agent_id": identity.id,
        "kid": runtime.agent_kid,
        "profile_url": identity.profile_url,
        "trusted": identity.trusted,
        "public_jwk": dict(identity.public_jwk),
    }


@router.post("/agent/purchase")
def purchase(request: Request, body: AgentPurchaseRequest) -> dict[str, Any]:
    runtime = runtime_of(request)
    if runtime.core.mandate(body.mandate_id) is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    agent = PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid)
    run = agent.run(mandate_id=body.mandate_id, instruction=body.instruction)
    return {
        "outcome": run.outcome,
        "reason_code": run.reason_code,
        "human_summary": run.human_summary,
        "offer": run.offer,
        "escalation_id": run.escalation_id,
        "reservation_id": run.reservation_id,
        "settlement_reference": run.settlement_reference,
        "authorization_proof": run.authorization_proof,
        "offers_considered": run.considered,
        # Who proposed, and the reason it gave. The core never read either.
        "proposed_by": run.proposed_by,
        "rationale": run.rationale,
        "alternatives": [{"sku": sku, "reason": reason} for sku, reason in run.alternatives],
        # The same ladder /authorize publishes. This is the surface a judge attacks
        # in free text, so it is the one that most needs to explain itself.
        "evaluation_trace": [step.as_dict() for step in run.trace],
    }

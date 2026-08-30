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
from aval.agent.watches import WatchService
from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError

router = APIRouter(tags=["agent"])


class AgentPurchaseRequest(BaseModel):
    mandate_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


class RegisterWatchRequest(BaseModel):
    """A standing order. Same free text a person would type, kept for later."""

    mandate_id: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=500)


def _watches(request: Request) -> WatchService:
    runtime = runtime_of(request)
    return WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )


def _watch_view(watch) -> dict[str, Any]:
    return {
        "watch_id": watch.id,
        "mandate_id": watch.mandate_id,
        "instruction": watch.instruction,
        "status": watch.status.value,
        "outcome": watch.outcome,
        "settlement_reference": watch.settlement_reference,
        "created_at": watch.created_at,
        "expires_at": watch.expires_at,
        "closed_at": watch.closed_at,
    }


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


@router.post("/agent/watches", status_code=201)
def register_watch(request: Request, body: RegisterWatchRequest) -> dict[str, Any]:
    """Keep looking. Registering authorizes nothing — firing still asks the core."""
    try:
        watch = _watches(request).register(
            mandate_id=body.mandate_id, instruction=body.instruction
        )
    except ValueError as error:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.") from error
    return _watch_view(watch)


@router.get("/agent/watches")
def list_watches(request: Request, mandate_id: str) -> dict[str, Any]:
    return {"watches": [_watch_view(watch) for watch in _watches(request).for_mandate(mandate_id)]}


@router.post("/agent/watches/tick")
def tick_watches(request: Request, body: dict) -> dict[str, Any]:
    """Try every open watch once. This is where the agent acts with nobody watching."""
    mandate_id = str(body.get("mandate_id", ""))
    if not mandate_id:
        raise ApiError(422, "mandate_id_required", "mandate_id é obrigatório.")
    outcomes = _watches(request).tick(mandate_id)
    return {
        "fired": [
            {
                **_watch_view(outcome.watch),
                # An expired watch never asked, so there is no purchase to report.
                "purchase": None
                if outcome.run is None
                else {
                    "outcome": outcome.run.outcome,
                    "reason_code": outcome.run.reason_code,
                    "human_summary": outcome.run.human_summary,
                    "offer": outcome.run.offer,
                    "settlement_reference": outcome.run.settlement_reference,
                    "reservation_id": outcome.run.reservation_id,
                    "escalation_id": outcome.run.escalation_id,
                    "proposed_by": outcome.run.proposed_by,
                    "rationale": outcome.run.rationale,
                },
            }
            for outcome in outcomes
        ]
    }

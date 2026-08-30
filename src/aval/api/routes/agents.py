"""Agent profile registration.

Trust is recorded here, not inferred at call time — which makes this table the root of
the impostor defence. Everything `require_signed_agent` concludes rests on these rows,
so writing one is an operator action, never an anonymous one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import require_operator
from aval.domain.entities import AgentIdentity

router = APIRouter(tags=["agents"])


class RegisterAgentRequest(BaseModel):
    id: str = Field(min_length=1)
    profile_url: str = Field(min_length=1)
    public_jwk: dict[str, str]
    trusted: bool = False


class RegisterAgentResponse(BaseModel):
    agent_id: str
    kid: str
    trusted: bool


@router.post(
    "/agents",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterAgentResponse,
    dependencies=[Depends(require_operator)],
)
def register_agent(request: Request, body: RegisterAgentRequest) -> RegisterAgentResponse:
    kid = body.public_jwk.get("kid")
    if not kid:
        raise ApiError(422, "agent_key_without_kid", "A chave do agente precisa de um kid.")
    core = runtime_of(request).core
    # A key id is how a signature names itself. Letting a second profile claim one that
    # is already taken would make `agent_for_kid` answer with whichever row it happened
    # to scan first — a stranger could then answer for the real agent.
    existing = core.agent_for_kid(kid)
    if existing is not None and existing.id != body.id:
        raise ApiError(
            409, "agent_kid_already_registered", "Este kid já pertence a outro perfil."
        )
    # The profile URL is unique in the store, so a second agent claiming one is answered
    # here rather than surfacing as a constraint violation from the database.
    claimed = core.agent_for_profile_url(body.profile_url)
    if claimed is not None and claimed.id != body.id:
        raise ApiError(
            409, "agent_profile_url_taken", "Esta profile_url já pertence a outro perfil."
        )
    core.register_agent(
        AgentIdentity(
            id=body.id,
            profile_url=body.profile_url,
            public_jwk=dict(body.public_jwk),
            trusted=body.trusted,
        )
    )
    return RegisterAgentResponse(agent_id=body.id, kid=kid, trusted=body.trusted)


@router.get("/agents/{agent_kid}", response_model=RegisterAgentResponse)
def read_agent(request: Request, agent_kid: str) -> RegisterAgentResponse:
    """Public on purpose: a key id and its trust status are what a verifier checks."""
    identity = runtime_of(request).core.agent_for_kid(agent_kid)
    if identity is None:
        raise ApiError(404, "key_not_found", "Chave de agente desconhecida.")
    return RegisterAgentResponse(agent_id=identity.id, kid=agent_kid, trusted=identity.trusted)

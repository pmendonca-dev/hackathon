"""The edge check that answers *who is calling*.

This runs before any route body is parsed and before the core is consulted. It is the
only place in the system that decides whether a caller is the agent it claims to be —
and it decides nothing else. An agent that passes here still gets exactly what the
mandate allows and nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.domain.entities import AgentIdentity
from aval.runtime import AvalRuntime
from aval.security.http_signature import SignatureError, verify_request
from aval.security.key_custody import public_key_from_jwk

# A profile that exists but is not trusted is an authorisation problem, not an
# authentication one: we know exactly who is calling, and the answer is still no.
FORBIDDEN_REASONS = frozenset({"profile_not_trusted"})


def verify_signed_request(
    runtime: AvalRuntime,
    *,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
) -> AgentIdentity:
    """Verify one signed agent request. Raises ApiError with the reason to answer with."""
    found: dict[str, AgentIdentity] = {}

    def public_key_for(keyid: str):
        identity = runtime.core.agent_for_kid(keyid)
        if identity is None:
            raise SignatureError("key_not_found", "Chave de agente desconhecida.")
        if not identity.trusted:
            raise SignatureError("profile_not_trusted", "Perfil de agente não confiável.")
        try:
            key = public_key_from_jwk(dict(identity.public_jwk))
        except ValueError as error:
            raise SignatureError(
                "agent_key_unsupported", "Chave do perfil do agente não suportada."
            ) from error
        found["identity"] = identity
        return key

    try:
        verify_request(
            method=method,
            path=path,
            body=body,
            headers={key.lower(): value for key, value in headers.items()},
            public_key_for=public_key_for,
            now_epoch=int(runtime.clock.now().timestamp()),
            seen=runtime.replay_guard,
        )
    except SignatureError as error:
        status = 403 if error.reason_code in FORBIDDEN_REASONS else 401
        raise ApiError(status, error.reason_code, error.human_summary) from error
    return found["identity"]


async def require_signed_agent(request: Request) -> AgentIdentity:
    runtime = runtime_of(request)
    identity = verify_signed_request(
        runtime,
        method=request.method,
        path=request.url.path,
        body=await request.body(),
        headers=request.headers,
    )
    request.state.agent_identity = identity
    return identity

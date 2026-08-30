"""Operator authentication for the surfaces that are not agent traffic.

Two different questions are answered in this system by two different mechanisms, and
they must not be confused:

- *Is this the agent it claims to be?* — RFC 9421 signature, in `agent_auth`.
- *Is this the operator running this instance?* — a bearer token, here.

The operator token guards registration and the processor switch. It deliberately does
**not** guard anything that changes what a mandate may spend: that authority belongs to
the mandate holder and is proved with the holder's own key, never with an operator
credential. An operator who could raise a limit would be an operator who could spend
someone else's money.
"""

from __future__ import annotations

import hmac

from fastapi import Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError

OPERATOR_HEADER = "X-Aval-Operator"


def require_operator(request: Request) -> None:
    presented = request.headers.get(OPERATOR_HEADER, "")
    if not presented:
        raise ApiError(401, "operator_token_missing", "Credencial de operador ausente.")
    # Constant-time: a byte-by-byte comparison would let a caller find the token one
    # character at a time.
    if not hmac.compare_digest(presented, runtime_of(request).operator_token):
        raise ApiError(403, "operator_token_invalid", "Credencial de operador inválida.")

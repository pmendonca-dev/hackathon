"""Operator authentication for the surfaces that are not agent traffic.

Three different questions are answered in this system by three different mechanisms,
and they must not be confused:

- *Is this the agent it claims to be?* — RFC 9421 signature, in `agent_auth`.
- *May this purchase happen?* — the mandate, evaluated by the core.
- *Is this the operator running this instance?* — a bearer credential, here.

The operator credential guards registration, the processor switch, the demo clock and
the price knob. It deliberately does **not** guard anything that changes what a mandate
may spend: that authority belongs to the mandate holder and is proved with the holder's
own key, never with an operator credential. An operator who could raise a limit would be
an operator who could spend someone else's money.

Two things are new beside that old rule, and neither of them widens it.

**Sessions.** The raw token is a permanent secret, and the browser console needs one to
flip the processor in front of a judge. Shipping the token into the bundle publishes it:
anyone who opens devtools on the demo page keeps it forever. So the token is presented
once, at `POST /admin/operator/sessions`, and what the page holds is a short-lived credential
that expires on its own and can be closed. The raw token still works for machine callers
— the smoke script and CI have no browser to be stolen from.

**A journal.** Nobody signs to operate, so operator actions are the one authority here
with no cryptographic author. What replaces the signature is a hash chain: it cannot
prove who typed, and it can prove that nothing was quietly removed afterwards. Writes
are journaled; reads are not, because a journal that recorded its own reads would bury
the three lines that matter.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

from fastapi import Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.infrastructure.sqlite.operator_repository import (
    SqliteOperatorJournal,
    SqliteOperatorSessions,
)
from aval.infrastructure.sqlite.transaction import run_in_write_transaction

OPERATOR_HEADER = "X-Aval-Operator"
OPERATOR_SESSION_HEADER = "X-Aval-Operator-Session"
DEFAULT_SESSION_TTL_SECONDS = 1800

#: Methods that change something. A read is not an act of operation, and journaling one
#: would grow the chain without adding a fact anyone needs.
JOURNALLED_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def wall_clock_now() -> datetime:
    """Real time, deliberately not the demo clock.

    Everything about *mandates* is read against the runtime clock, because a judge is
    invited to move it and watch validity end. An operator session is a different kind
    of fact: it is about who is holding this console right now. Tying it to the demo
    clock had two consequences, both found by running the browser journey rather than
    the unit tests — a judge who advanced the clock to expire a mandate logged
    themselves out mid-demonstration, and an operator could end *another* operator's
    session by turning a knob that is supposed to age mandates and nothing else.
    """
    return datetime.now(UTC)


def session_ttl_seconds() -> int:
    """How long a console session lives. Short by default: the credential exists to be
    forgotten, and a judge who needs longer opens another one."""
    raw = os.environ.get("AVAL_OPERATOR_SESSION_TTL_SECONDS", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return DEFAULT_SESSION_TTL_SECONDS
    return int(raw)


def authenticated_operator(request: Request) -> str:
    """Who is operating: the raw token, or a named session. Refuses anything else."""
    runtime = runtime_of(request)
    session_token = request.headers.get(OPERATOR_SESSION_HEADER, "")
    if session_token:
        now = wall_clock_now()
        with runtime.engine.connect() as connection:
            try:
                session_id = SqliteOperatorSessions(connection).authenticate(
                    session_token, now=now
                )
            except ValueError as error:
                raise ApiError(
                    403,
                    str(error),
                    "Sessão de operador inválida ou expirada.",
                ) from error
        return f"operator:session:{session_id}"

    presented = request.headers.get(OPERATOR_HEADER, "")
    if not presented:
        raise ApiError(401, "operator_token_missing", "Credencial de operador ausente.")
    # Constant-time: a byte-by-byte comparison would let a caller find the token one
    # character at a time.
    if not hmac.compare_digest(presented, runtime.operator_token):
        raise ApiError(403, "operator_token_invalid", "Credencial de operador inválida.")
    return "operator:token"


def require_operator(request: Request) -> str:
    """Authenticate the operator and, for a write, record that it happened."""
    actor = authenticated_operator(request)
    if request.method.upper() in JOURNALLED_METHODS:
        runtime = runtime_of(request)
        action = f"{request.method.upper()} {request.url.path}"
        run_in_write_transaction(
            runtime.engine,
            lambda connection: SqliteOperatorJournal(connection).append(
                action=action,
                actor=actor,
                # Query only. A body can carry a card number, and the journal is read
                # by anyone holding an operator credential — it records *that the
                # instance was operated*, never what a person typed into it.
                detail={"query": dict(request.query_params)},
                occurred_at=runtime.clock.now(),
            ),
        )
    return actor

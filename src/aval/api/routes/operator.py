"""The operator's own surfaces: a session to hold, and the record of what was done.

Neither route can move money. `POST /admin/operator/sessions` trades the permanent token for
a short-lived one so that no console has to carry the permanent one, and
`GET /admin/operator/journal` publishes the chain of what operator credentials did — including
the actions taken by the session that is reading it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import (
    OPERATOR_SESSION_HEADER,
    authenticated_operator,
    require_operator,
    session_ttl_seconds,
    wall_clock_now,
)
from aval.infrastructure.sqlite.operator_repository import (
    SqliteOperatorJournal,
    SqliteOperatorSessions,
    verify_journal,
)
from aval.infrastructure.sqlite.transaction import run_in_write_transaction

router = APIRouter(tags=["operator"])


@router.post("/admin/operator/sessions", status_code=status.HTTP_201_CREATED)
def open_session(request: Request) -> dict[str, Any]:
    """Trade the operator token for a credential a browser may hold.

    Deliberately *not* reachable with a session: a session that could mint sessions
    would be a permanent credential wearing a short-lived name.
    """
    runtime = runtime_of(request)
    if request.headers.get(OPERATOR_SESSION_HEADER):
        raise ApiError(
            403,
            "operator_session_cannot_extend_itself",
            "A session does not open another session; present the token.",
        )
    authenticated_operator(request)
    issued = run_in_write_transaction(
        runtime.engine,
        lambda connection: SqliteOperatorSessions(connection).issue(
            now=wall_clock_now(), ttl_seconds=session_ttl_seconds()
        ),
    )
    return {
        "session_id": issued.id,
        "session_token": issued.token,
        "expires_at": issued.expires_at.isoformat(),
    }


@router.delete("/admin/operator/sessions/current")
def close_session(request: Request, actor: str = Depends(require_operator)) -> dict[str, Any]:
    """End this session now, without waiting for it to expire."""
    if not actor.startswith("operator:session:"):
        raise ApiError(
            400,
            "operator_session_absent",
            "There is no session to end: this call used the token.",
        )
    runtime = runtime_of(request)
    session_id = actor.split("operator:session:", 1)[1]
    run_in_write_transaction(
        runtime.engine,
        lambda connection: SqliteOperatorSessions(connection).revoke(
            session_id, now=wall_clock_now()
        ),
    )
    return {"session_id": session_id, "status": "closed"}


@router.get("/admin/operator/journal")
def read_journal(request: Request, _: str = Depends(require_operator)) -> dict[str, Any]:
    """Every operator action, in order, with the chain that proves none was removed."""
    runtime = runtime_of(request)
    with runtime.engine.connect() as connection:
        entries = SqliteOperatorJournal(connection).entries()
    intact, broken_at = verify_journal(entries)
    return {
        "entries": [
            {
                "sequence": entry.sequence,
                "action": entry.action,
                "actor": entry.actor,
                "detail": entry.detail,
                "occurred_at": entry.occurred_at.isoformat(),
                "sha256": entry.sha256,
                "previous_sha256": entry.previous_sha256,
            }
            for entry in entries
        ],
        "chain": {"intact": intact, "checked": len(entries), "broken_at": broken_at},
    }

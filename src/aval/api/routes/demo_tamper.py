"""A deliberately destructive demonstration tool: edit one audit event in place.

The point of the hash chain is that nobody has to trust the operator not to edit the
log — the log catches the edit. That claim is worth exactly as much as a judge's
ability to test it, so this route lets them break a link and watch `/ledger/verify`
name the position.

It is never mounted unless `AVAL_DEMO_TAMPER` is set. That is not a permission check
that can be argued with or misconfigured into permissiveness: without the variable the
router is never included, so the path 404s and never appears in the OpenAPI document.
On top of that it requires the operator token, and it can only ever corrupt — there is
no repair counterpart, because a route that could rewrite the chain into a valid state
would destroy the property this one exists to prove.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import require_operator
from aval.infrastructure.sqlite.models import audit_events, evidence
from aval.security.jcs import canonicalize

TAMPER_FLAG = "AVAL_DEMO_TAMPER"


def tampering_enabled() -> bool:
    return os.environ.get(TAMPER_FLAG, "").strip() not in ("", "0", "false", "False")


class TamperRequest(BaseModel):
    sequence: int


def create_demo_tamper_router() -> APIRouter:
    router = APIRouter(tags=["demo"])

    @router.post(
        "/admin/ledger/{mandate_id}/tamper", dependencies=[Depends(require_operator)]
    )
    def tamper(request: Request, mandate_id: str, body: TamperRequest) -> dict[str, Any]:
        """Rewrite the stored canonical bytes of one event, leaving its digest behind.

        This edits exactly what the auditor re-hashes, which is what makes the break
        real rather than staged: the row now disagrees with the hash that was taken
        over it, and every later link inherits the mismatch through `previous_sha256`.
        Editing a column outside the hashed record would corrupt nothing and would let
        the demonstration claim a property the chain does not actually have.
        """
        runtime = runtime_of(request)
        with runtime.engine.begin() as connection:
            row = connection.execute(
                select(audit_events.c.evidence_id)
                .where(
                    audit_events.c.mandate_id == mandate_id,
                    audit_events.c.sequence == body.sequence,
                )
            ).mappings().one_or_none()
            if row is None or row["evidence_id"] is None:
                raise ApiError(404, "audit_event_not_found", "Evento não encontrado na trilha.")
            payload = connection.execute(
                select(evidence.c.payload).where(evidence.c.id == row["evidence_id"])
            ).scalar_one()
            # Rewrite who did it, and re-canonicalise, so the row still reads as a
            # well-formed record. That is the interesting case: the forgery is not
            # obvious by inspection, and it is caught only because the digest taken at
            # write time no longer matches the bytes now on disk.
            record = json.loads(payload)
            record["actor"] = "operador-mal-intencionado"
            connection.execute(
                update(evidence)
                .where(evidence.c.id == row["evidence_id"])
                .values(payload=canonicalize(record).decode("utf-8"))
            )
        intact, broken_at, checked = runtime.core.verify_timeline(mandate_id)
        return {
            "tampered_sequence": body.sequence,
            "chain": {"intact": intact, "broken_at": broken_at, "checked": checked},
        }

    return router

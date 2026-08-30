"""Operator surfaces: the processor switch, reconciliation and disputes.

`/admin/psp` is a judge surface. It exists so the failure story can be demonstrated
rather than described: turn the processor off, watch a purchase land in doubt with the
budget still held, turn it back on, reconcile.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import require_operator
from aval.domain.errors import DomainError
from aval.infrastructure.psp import MODES

router = APIRouter(tags=["operations"])


class PspModeRequest(BaseModel):
    mode: Literal["online", "offline", "decline"]


class OpenDisputeRequest(BaseModel):
    reservation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/admin/psp", dependencies=[Depends(require_operator)])
def set_psp_mode(request: Request, body: PspModeRequest) -> dict[str, Any]:
    runtime_of(request).psp_control.mode = body.mode
    return {"mode": body.mode, "modes": list(MODES)}


@router.get("/admin/psp", dependencies=[Depends(require_operator)])
def read_psp_mode(request: Request) -> dict[str, Any]:
    return {"mode": runtime_of(request).psp_control.mode, "modes": list(MODES)}


@router.post("/reconcile", dependencies=[Depends(require_operator)])
def reconcile(request: Request) -> dict[str, int]:
    return runtime_of(request).core.reconcile()


@router.post("/disputes", status_code=status.HTTP_201_CREATED)
def open_dispute(request: Request, body: OpenDisputeRequest) -> dict[str, Any]:
    try:
        dispute = runtime_of(request).core.open_dispute(
            reservation_id=body.reservation_id, reason=body.reason
        )
    except ValueError as error:
        raise ApiError(404, "reservation_not_found", "Compra não encontrada.") from error
    return {"dispute_id": dispute.id, "status": dispute.status.value, "reason": dispute.reason}


@router.get("/disputes")
def list_disputes(request: Request, mandate_id: str) -> dict[str, Any]:
    core = runtime_of(request).core
    if core.mandate(mandate_id) is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    return {
        "mandate_id": mandate_id,
        "disputes": [
            {
                "id": dispute.id,
                "reservation_id": dispute.reservation_id,
                "reason": dispute.reason,
                "status": dispute.status.value,
                "resolution": dispute.resolution,
                "opened_at": dispute.opened_at.isoformat(),
                "resolved_at": None
                if dispute.resolved_at is None
                else dispute.resolved_at.isoformat(),
            }
            for dispute in core.disputes_for_mandate(mandate_id)
        ],
    }


@router.post("/disputes/{dispute_id}/resolution")
def resolve_dispute(request: Request, dispute_id: str) -> dict[str, Any]:
    """Resolved by reading the trail, not by taking anybody's word for it."""
    try:
        dispute = runtime_of(request).core.resolve_dispute(dispute_id)
    except DomainError as error:
        raise ApiError(409, "dispute_already_resolved", "Disputa já resolvida.") from error
    except ValueError as error:
        raise ApiError(404, "dispute_not_found", "Disputa não encontrada.") from error
    return {
        "dispute_id": dispute.id,
        "status": dispute.status.value,
        "resolution": dispute.resolution,
    }

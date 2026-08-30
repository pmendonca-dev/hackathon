"""Operator surfaces: the processor switch, reconciliation and disputes.

`/admin/psp` is a judge surface. It exists so the failure story can be demonstrated
rather than described: turn the processor off, watch a purchase land in doubt with the
budget still held, turn it back on, reconcile.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.operator_auth import require_operator
from aval.domain.errors import DomainError
from aval.infrastructure.psp import MODES
from aval.merchant.catalog import CATALOG

router = APIRouter(tags=["operations"])


class PspModeRequest(BaseModel):
    mode: Literal["online", "offline", "decline"]


class AdvanceClockRequest(BaseModel):
    """Seconds to move forward. Negative and zero are refused by the route."""

    advance_seconds: int


class RepriceRequest(BaseModel):
    """A seller changing its own price, which is the world moving under the agent."""

    sku: str = Field(min_length=1)
    minor_units: int = Field(gt=0)


class OpenDisputeRequest(BaseModel):
    reservation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


@router.post("/admin/catalog/price", dependencies=[Depends(require_operator)])
def reprice(request: Request, body: RepriceRequest) -> dict[str, Any]:
    """Drop a price and watch what the agent does about it.

    This is the judge surface the standing order needs: the case's scenario begins with
    a price that has not fallen yet, and there is no way to demonstrate an agent that
    waits without something that makes the waiting end.
    """
    runtime = runtime_of(request)
    if not any(item.sku == body.sku for item in CATALOG):
        raise ApiError(404, "sku_not_found", "SKU não existe no catálogo.")
    runtime.offers.reprice(body.sku, body.minor_units)
    return {"sku": body.sku, "minor_units": body.minor_units}


@router.post("/admin/psp", dependencies=[Depends(require_operator)])
def set_psp_mode(request: Request, body: PspModeRequest) -> dict[str, Any]:
    runtime_of(request).psp_control.mode = body.mode
    return {"mode": body.mode, "modes": list(MODES)}


@router.get("/admin/psp", dependencies=[Depends(require_operator)])
def read_psp_mode(request: Request) -> dict[str, Any]:
    return {"mode": runtime_of(request).psp_control.mode, "modes": list(MODES)}


@router.post("/admin/clock", dependencies=[Depends(require_operator)])
def advance_clock(request: Request, body: AdvanceClockRequest) -> dict[str, Any]:
    """Move the demo clock forward so expiry can be demonstrated rather than awaited.

    Forward only. Rewinding would revive an expired mandate, which is granting spending
    authority — and no operator credential does that in this system. The refusal is a
    422 rather than a clamp, because silently ignoring the sign would let a judge
    believe they had rewound time when they had not.
    """
    runtime = runtime_of(request)
    try:
        offset = runtime.clock.advance(timedelta(seconds=body.advance_seconds))
    except ValueError as error:
        raise ApiError(
            422,
            "clock_moves_forward_only",
            "O relógio da demonstração só avança; rebobinar reviveria um mandato expirado.",
        ) from error
    return {"now": runtime.clock.now().isoformat(), "offset_seconds": int(offset.total_seconds())}


@router.get("/admin/clock", dependencies=[Depends(require_operator)])
def read_clock(request: Request) -> dict[str, Any]:
    runtime = runtime_of(request)
    return {
        "now": runtime.clock.now().isoformat(),
        "offset_seconds": int(runtime.clock.offset.total_seconds()),
    }


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
                "liability": core.liability_for(dispute.reservation_id),
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
        # "Was this authorized?" and "who answers for it?" are different questions.
        # The first is the status above; this is the second.
        #
        # Read from the trail rather than recomputed: when the verdict does not put the
        # charge on the holder it also gives the money back, and a fresh computation
        # would then answer NO_CHARGE — true about the world after the reversal, and not
        # what this resolution decided.
        "liability": (
            runtime_of(request).core.liability_recorded_for(dispute.id)
            or runtime_of(request).core.liability_for(dispute.reservation_id)
        ),
    }


@router.get("/metrics")
def read_metrics(request: Request) -> dict[str, Any]:
    """The footer the pitch runs on: aggregates of the trail, plus edge instrumentation.

    Unauthenticated on purpose. Everything here is a count or a duration for the whole
    instance — no mandate, no principal, no merchant, no amount attributable to anyone.
    The one money figure is `spend_outside_mandate`, which is an invariant that reads
    zero rather than anybody's balance.
    """
    runtime = runtime_of(request)
    return {**runtime.core.metrics_snapshot(), **runtime.metrics.snapshot()}

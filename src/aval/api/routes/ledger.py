"""Reading the trail, and checking that it has not been edited.

Nothing here computes a decision. It reads what the core already wrote and projects
it for one audience.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.schemas import MandateListView, MandateView, MoneyOut, UsageLimitOut
from aval.application.authorization_core import MandateSnapshot
from aval.application.ledger_views import (
    MERCHANT_REDACTIONS,
    auditor_entry,
    human_entry,
    merchant_entry,
)

router = APIRouter(tags=["ledger"])


def mandate_view(snapshot: MandateSnapshot) -> MandateView:
    mandate = snapshot.mandate
    return MandateView(
        mandate_id=mandate.id,
        status=mandate.status.value,
        principal={"id": mandate.principal.id, "display_name": mandate.principal.display_name},
        allowed_merchant_ids=sorted(mandate.allowed_merchant_ids),
        allowed_categories=sorted(mandate.allowed_categories),
        limit=MoneyOut.of(snapshot.limit),
        ceiling=None if mandate.ceiling is None else MoneyOut.of(mandate.ceiling),
        spent=MoneyOut.of(snapshot.spent),
        remaining=MoneyOut.of(snapshot.remaining),
        expires_at=mandate.expires_at,
        policy_version=mandate.policy_version,
        revocation_epoch=int(mandate.revocation_metadata.get("epoch", 0)),
        usage_limit=(
            None
            if mandate.usage_limit is None
            else UsageLimitOut(
                max_uses=mandate.usage_limit.max_uses,
                window_seconds=mandate.usage_limit.window_seconds,
            )
        ),
        uses_in_window=snapshot.uses_in_window,
        instrument_label=None if mandate.instrument is None else mandate.instrument.label,
    )


@router.get("/mandates", response_model=MandateListView)
def list_mandates(
    request: Request,
    principal_id: str = Query(
        ...,
        min_length=1,
        description="Whose mandates to list. Required: there is no global listing.",
    ),
) -> MandateListView:
    """The mandates one buyer holds.

    `principal_id` is mandatory, and that is a security decision rather than an
    ergonomic one. An unscoped listing would hand any caller every buyer in the system,
    their limits, their spend and their merchants — the same disclosure the merchant
    view is built to withhold. A holder with no mandates gets an empty list, not a 404:
    absence of mandates is not an error, and answering differently would turn this into
    an oracle for which principal ids exist.
    """
    core = runtime_of(request).core
    return MandateListView(
        principal_id=principal_id,
        mandates=[mandate_view(snapshot) for snapshot in core.snapshots_for_principal(principal_id)],
    )


@router.get("/mandates/{mandate_id}", response_model=MandateView)
def read_mandate(request: Request, mandate_id: str) -> MandateView:
    snapshot = runtime_of(request).core.snapshot(mandate_id)
    if snapshot is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    return mandate_view(snapshot)


@router.get("/ledger")
def read_ledger(
    request: Request,
    view: Literal["human", "merchant", "auditor"] = Query(...),
    mandate_id: str | None = None,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    core = runtime_of(request).core
    if view == "merchant":
        # A merchant is answered by its own name, never by a mandate id. Accepting one
        # here would hand it the identifier the whole view exists to withhold.
        if not merchant_id:
            raise ApiError(
                400,
                "merchant_view_requires_merchant_id",
                "A visão do merchant é consultada por merchant_id.",
            )
        entries = core.merchant_timeline(merchant_id)
        return {
            "view": "merchant",
            "merchant_id": merchant_id,
            "entries": [merchant_entry(entry) for entry in entries],
            "redacted": list(MERCHANT_REDACTIONS),
        }

    if not mandate_id:
        raise ApiError(400, "mandate_id_required", "Informe o mandate_id.")
    snapshot = core.snapshot(mandate_id)
    if snapshot is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    entries = core.timeline_for(mandate_id)

    if view == "human":
        return {
            "view": "human",
            "mandate": mandate_view(snapshot).model_dump(mode="json"),
            "entries": [human_entry(entry) for entry in entries],
        }

    intact, broken_at, checked = core.verify_timeline(mandate_id)
    return {
        "view": "auditor",
        "mandate": mandate_view(snapshot).model_dump(mode="json"),
        "entries": [auditor_entry(entry) for entry in entries],
        "chain": {"intact": intact, "checked": checked, "broken_at": broken_at},
    }


@router.get("/ledger/verify")
def verify_ledger(request: Request, mandate_id: str) -> dict[str, Any]:
    core = runtime_of(request).core
    if core.mandate(mandate_id) is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    intact, broken_at, checked = core.verify_timeline(mandate_id)
    return {"intact": intact, "checked": checked, "broken_at": broken_at}

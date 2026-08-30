"""Reading the trail, and checking that it has not been edited.

Nothing here computes a decision. It reads what the core already wrote and projects
it for one audience.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError
from aval.api.holder_authority import require_holder_authority
from aval.api.schemas import MandateListView, MandateView, MoneyOut, UsageLimitOut
from aval.application.authorization_core import MandateSnapshot
from aval.security.pairwise import pairwise_id
from aval.application.ledger_views import (
    MERCHANT_REDACTIONS,
    MERCHANT_VISIBLE_EVENTS,
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
        instrument_revoked=snapshot.instrument_revoked,
    )


@router.get("/mandates", response_model=MandateListView)
def list_mandates(
    request: Request,
    principal_id: str = Query(
        ...,
        min_length=1,
        description="Whose mandates to list. Required: there is no global listing.",
    ),
    authorization_jws: str = Query(
        ...,
        min_length=1,
        description="Compact JWS ES256 by a holder authority, over {principal_id}.",
    ),
) -> MandateListView:
    """The mandates one buyer holds, scoped to the key that may see them.

    `principal_id` alone was never a secret. The bot derives it as `usr_tg_{chat_id}`
    and the browser defaults it to `usr_marta`, so a name that anyone can guess was
    handing out a buyer's limits, spend and merchants. Authority was always isolated —
    one judge cannot revoke another's mandate — but sight was not, and a room of judges
    sharing one bot is exactly the situation this system was built for.

    So the listing is scoped by the *key*, not by the name: the signature is verified
    against each mandate's own holder authority, and the answer is the intersection. A
    key that holds nothing sees nothing, which is also what a holder gets before they
    have created their first mandate — no refusal, and no oracle for which buyers exist.
    """
    core = runtime_of(request).core
    try:
        readable = set(core.mandates_readable_by(authorization_jws, principal_id))
    except ValueError as error:
        raise ApiError(
            422, "read_authorization_malformed", "Autorização de leitura malformada."
        ) from error
    return MandateListView(
        principal_id=principal_id,
        mandates=[
            mandate_view(snapshot)
            for snapshot in core.snapshots_for_principal(principal_id)
            if snapshot.mandate.id in readable
        ],
    )


def require_read_authority(request: Request, mandate_id: str, authorization_jws: str | None):
    """Sight of one mandate, proved by a key that mandate names.

    The same rule the listing already applied, now on the surfaces that answer for a
    single mandate. `mandate_id` was never a secret — it travels in the agent's receipt,
    in the address bar and in any screenshot — so the id alone was handing out a
    person's budget, spend, merchants and purchase history.

    The refusals are deliberately different from the listing's empty answer: here the
    caller already names one mandate, so "you may not read this" leaks nothing that
    naming it did not.
    """
    require_holder_authority(
        request,
        mandate_id,
        authorization_jws,
        unsigned_message="A leitura deste registro exige autorização assinada pelo titular.",
    )
    return runtime_of(request).core.snapshot(mandate_id)


@router.get("/mandates/{mandate_id}", response_model=MandateView)
def read_mandate(
    request: Request,
    mandate_id: str,
    authorization_jws: str | None = Query(
        default=None,
        description="Compact JWS ES256 by a holder authority of this mandate.",
    ),
) -> MandateView:
    return mandate_view(require_read_authority(request, mandate_id, authorization_jws))


@router.get("/ledger")
def read_ledger(
    request: Request,
    view: Literal["human", "merchant", "auditor"] = Query(...),
    mandate_id: str | None = None,
    merchant_id: str | None = None,
    authorization_jws: str | None = Query(
        default=None,
        description="Holder signature, required by the human view and by nothing else.",
    ),
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
        secret = runtime_of(request).pairwise_secret

        def pairwise(mandate: str, seller: str) -> str:
            return pairwise_id(secret, mandate_id=mandate, merchant_id=seller)

        return {
            "view": "merchant",
            "merchant_id": merchant_id,
            "entries": [
                merchant_entry(entry, pairwise=pairwise)
                for entry in entries
                if entry.event_type in MERCHANT_VISIBLE_EVENTS
            ],
            "redacted": list(MERCHANT_REDACTIONS),
        }

    if not mandate_id:
        raise ApiError(400, "mandate_id_required", "Informe o mandate_id.")
    snapshot = core.snapshot(mandate_id)
    if snapshot is None:
        raise ApiError(404, "mandate_not_found", "Mandato não encontrado.")
    entries = core.timeline_for(mandate_id)

    if view == "human":
        # The auditor view stays open on purpose — it is the transparency surface, and
        # what it publishes is the chain a judge is invited to check. The person's own
        # record is a different thing: it names limits, spend and what they bought.
        require_read_authority(request, mandate_id, authorization_jws)
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

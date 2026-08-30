"""The purchase pipeline, shared by the HTTP routes and the in-process agent.

Both callers arrive here with an already-verified agent identity. Keeping the pipeline
in one place is what makes the in-process agent honest: it is not a shortcut past the
edge, it is the same edge, called from the same code.
"""

from __future__ import annotations

from aval.api.offer_binding import bind_offer
from aval.api.schemas import CaptureRequest, PurchaseRequest
from aval.application.authorization_core import (
    AuthorizationCommand,
    AuthorizationResult,
    CaptureCommand,
    CaptureResult,
)
from aval.domain.entities import AgentIdentity
from aval.runtime import AvalRuntime


def authorize_purchase(
    runtime: AvalRuntime, *, agent: AgentIdentity, body: PurchaseRequest
) -> AuthorizationResult:
    if body.merchant_authorization:
        # A pre-check must not spend the offer: the purchase that follows still needs it.
        bind_offer(
            runtime,
            token=body.merchant_authorization,
            merchant_id=body.merchant_id,
            category=body.category,
            minor_units=body.total.minor_units,
            currency=body.total.currency,
            scale=body.total.scale,
            spend_nonce=False,
        )
    return runtime.core.decide(
        AuthorizationCommand(
            mandate_id=body.mandate_id,
            checkout_id=body.checkout_id,
            merchant_id=body.merchant_id,
            total=body.total.to_money(),
            category=body.category,
        ),
        agent_id=agent.id,
    )


def capture_purchase(
    runtime: AvalRuntime, *, agent: AgentIdentity, body: CaptureRequest
) -> CaptureResult:
    bound = None
    if body.merchant_authorization:
        bound = bind_offer(
            runtime,
            token=body.merchant_authorization,
            merchant_id=body.merchant_id,
            category=body.category,
            minor_units=body.total.minor_units,
            currency=body.total.currency,
            scale=body.total.scale,
            spend_nonce=True,
        )
    return runtime.core.capture(
        CaptureCommand(
            mandate_id=body.mandate_id,
            checkout_id=body.checkout_id,
            merchant_id=body.merchant_id,
            total=body.total.to_money(),
            category=body.category,
            idempotency_key=body.idempotency_key,
            # Only the verified offer names the terms. A purchase that carried none is
            # recorded with none, and the merchant's `terms_hash_matches` check refuses
            # it — which is the honest answer, not a hash the buyer chose for itself.
            terms_hash=None if bound is None else bound.terms_hash,
            canonical_offer=None if bound is None else bound.canonical_payload,
            instrument_id=body.instrument_id,
        ),
        agent_id=agent.id,
    )

"""The purchasing agent: discovers, decides, pays.

It holds a key of its own, separate from the human it acts for, and signs every
request it makes. It is free to propose anything — including things the mandate
forbids — because nothing it proposes is what decides the outcome.

The transport is deliberately explicit. In process it signs and hands the request to
the same verification the HTTP edge uses, so an agent running here has no privilege an
agent running elsewhere would not have.

Choosing what to buy lives in `proposer.py`; this file only carries the choice through
signing, authorization and capture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aval.agent.proposer import OfferProposer, Question, build_proposer
from aval.infrastructure.psp import PspUnreachable
from aval.api.purchase_flow import authorize_purchase, capture_purchase
from aval.api.schemas import CaptureRequest, PurchaseRequest
from aval.api.agent_auth import verify_signed_request
from aval.application.authorization_core import EvaluationStep
from aval.runtime import AvalRuntime
from aval.security.http_signature import sign_request
from aval.security.key_custody import KeyCustodyService


@dataclass(frozen=True)
class AgentRun:
    outcome: str
    reason_code: str
    human_summary: str
    offer: dict[str, Any] | None = None
    escalation_id: str | None = None
    reservation_id: str | None = None
    settlement_reference: str | None = None
    authorization_proof: str | None = None
    considered: int = 0
    # Who chose, and why. Shown to the human, never read by the core.
    proposed_by: str = "rules"
    rationale: str | None = None
    alternatives: tuple[tuple[str, str], ...] = ()
    # The authorization ladder the attempt ran into. Empty when no offer matched,
    # because nothing was ever put to the core.
    trace: tuple[EvaluationStep, ...] = ()


class PurchasingAgent:
    def __init__(
        self,
        runtime: AvalRuntime,
        *,
        custody: KeyCustodyService,
        kid: str,
        proposer: OfferProposer | None = None,
    ) -> None:
        self._runtime = runtime
        self._custody = custody
        self._kid = kid
        # Rules by default; a real model only when the team turned one on. Either
        # way the proposer proposes and the core disposes — swapping it changes
        # nothing about what may be bought, which is the whole architectural claim.
        self._proposer = proposer or build_proposer()

    def _signed_call(self, path: str, body: dict[str, Any]):
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = sign_request(
            method="POST",
            path=path,
            body=raw,
            custody=self._custody,
            kid=self._kid,
            created=int(self._runtime.clock.now().timestamp()),
        )
        # Same verification the HTTP edge runs. Being in-process buys no trust.
        return verify_signed_request(
            self._runtime, method="POST", path=path, body=raw, headers=headers
        )

    def run(
        self,
        *,
        mandate_id: str,
        instruction: str,
        offers: list[dict[str, Any]] | None = None,
        proposer: OfferProposer | None = None,
    ) -> AgentRun:
        # `offers` is how a real-offer watch hands over what a web search just found,
        # already signed by the test marketplace. None keeps the original path: shop the
        # seeded catalogue. Either way what arrives here is a list of signed offers, and
        # nothing below this line can tell — or needs to tell — where they came from.
        #
        # `proposer` travels with them because *how to choose* differs: the catalogue is
        # a table to be interpreted, while a search result is a shortlist the search
        # already interpreted. Neither choice is a decision — the core makes that one.
        offers = self._runtime.offers.catalog() if offers is None else offers
        proposal = (proposer or self._proposer).propose(instruction, offers)
        if isinstance(proposal, Question):
            # Not a refusal and not a purchase. The mandate was never consulted,
            # because there is nothing yet to put to it.
            return AgentRun(
                outcome="needs_clarification",
                reason_code="instruction_ambiguous",
                human_summary=proposal.text,
                considered=len(offers),
            )
        if proposal is None:
            return AgentRun(
                outcome="no_offer",
                reason_code="no_offer_matched",
                human_summary="No offer in the catalogue meets the request.",
                considered=len(offers),
            )
        offer = proposal.offer
        credit = {
            "proposed_by": proposal.proposed_by,
            "rationale": proposal.rationale or None,
            "alternatives": proposal.alternatives,
        }

        checkout_id = f"chk_{uuid4().hex[:12]}"
        purchase = {
            "mandate_id": mandate_id,
            "checkout_id": checkout_id,
            "merchant_id": offer["merchant_id"],
            "category": offer["item"]["category"],
            "total": offer["total"],
            "merchant_authorization": offer["merchant_authorization"],
        }

        agent = self._signed_call("/authorize", purchase)
        decision = authorize_purchase(
            self._runtime, agent=agent, body=PurchaseRequest(**purchase)
        )
        if decision.decision.value != "authorized":
            return AgentRun(
                outcome=decision.decision.value,
                reason_code=decision.reason_code,
                human_summary=decision.human_summary,
                offer=offer,
                escalation_id=decision.escalation_id,
                considered=len(offers),
                trace=decision.trace,
                **credit,
            )

        # The agent presents the mandate's own payment method. The token is worthless
        # anywhere else — the core refuses a capture that names a different one, and the
        # holder can cancel the card without touching the mandate — and it is not a PAN,
        # so an agent that leaks it has leaked nothing that can pay.
        snapshot = self._runtime.core.snapshot(mandate_id)
        instrument = None if snapshot is None else snapshot.mandate.instrument
        capture_body = {
            **purchase,
            "idempotency_key": f"cap_{checkout_id}",
            "instrument_id": None if instrument is None else instrument.token,
        }
        agent = self._signed_call("/capture", capture_body)
        try:
            result = capture_purchase(
                self._runtime, agent=agent, body=CaptureRequest(**capture_body)
            )
        except PspUnreachable:
            # The purchase is committed and the budget is held; only the processor's
            # answer is missing. `/capture` answers 502 because a machine caller has to
            # learn it got no answer — but a person is owed the state, not the error.
            # Reconciliation is what turns this into settled or declined.
            return AgentRun(
                outcome="in_doubt",
                reason_code="settlement_unreachable",
                human_summary=(
                    "Purchase authorized and in confirmation: the processor did not "
                    "answer. The budget stays held until reconciliation."
                ),
                offer=offer,
                considered=len(offers),
                trace=decision.trace,
                **credit,
            )
        return AgentRun(
            outcome="settled" if result.approved else "refused",
            reason_code=result.reason_code,
            human_summary=(
                f"Purchase of {offer['item']['title']} completed."
                if result.approved
                else "Purchase not completed."
            ),
            offer=offer,
            reservation_id=None if result.reservation is None else result.reservation.id,
            settlement_reference=result.settlement_reference,
            authorization_proof=result.authorization_proof,
            escalation_id=result.escalation_id,
            considered=len(offers),
            trace=decision.trace,
            **credit,
        )

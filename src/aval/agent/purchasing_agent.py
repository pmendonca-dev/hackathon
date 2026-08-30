"""The purchasing agent: discovers, decides, pays.

It holds a key of its own, separate from the human it acts for, and signs every
request it makes. It is free to propose anything — including things the mandate
forbids — because nothing it proposes is what decides the outcome.

The transport is deliberately explicit. In process it signs and hands the request to
the same verification the HTTP edge uses, so an agent running here has no privilege an
agent running elsewhere would not have.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aval.agent.intent import PurchaseIntent, fold, parse_intent
from aval.agent.llm_proposer import Proposal, configured, propose
from aval.api.errors import ApiError
from aval.api.purchase_flow import authorize_purchase, capture_purchase
from aval.api.schemas import CaptureRequest, PurchaseRequest
from aval.api.agent_auth import verify_signed_request
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


def shortlist(
    offers: list[dict[str, Any]], intent: PurchaseIntent, *, limit: int = 12
) -> list[dict[str, Any]]:
    """The candidates worth thinking hard about.

    Cheap and deterministic, and deliberately looser than `choose_offer`: it drops what
    the buyer said is too expensive and ranks the rest by how well the words and the
    category match, but it refuses nothing on category alone. A model that may only see
    flights can never propose the hotel — and never be caught proposing it.

    Every category that survived the price filter puts its best candidate on the list,
    even when it lost every slot to the category the buyer named. Without that, one
    popular route starves the shortlist and the model can never be caught proposing the
    hotel or the bundle — which is exactly the refusal the case asks us to demonstrate.

    It exists so this works with a catalogue of thousands: filter in code, rank the
    survivors with judgement.
    """
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    for position, offer in enumerate(offers):
        item = offer["item"]
        price = offer["total"]["minor_units"]
        if intent.max_minor_units is not None and price > intent.max_minor_units:
            continue
        haystack = fold(f"{item['title']} {item['sku']}")
        score = sum(1 for keyword in set(intent.keywords) if keyword in haystack)
        score += 1 if item["category"] == intent.category else 0
        # Position breaks ties so two identically priced offers never make this
        # comparison reach for the dicts themselves.
        ranked.append((-score, price, position, offer))
    ranked.sort(key=lambda entry: entry[:3])
    ordered = [entry[3] for entry in ranked]
    picked = ordered[:limit]
    seen = {offer["item"]["category"] for offer in picked}
    for offer in ordered[limit:]:
        if offer["item"]["category"] not in seen:
            seen.add(offer["item"]["category"])
            picked.append(offer)
    return picked


def choose_offer(offers: list[dict[str, Any]], intent: PurchaseIntent) -> dict[str, Any] | None:
    """Cheapest offer that matches the category, the words and the target price.

    The target price is the case's own example — *buy it if it drops below $150* — and
    it is enforced here, by the agent, as a preference. The mandate enforces its own
    limits separately; this one is the shopper being picky, not the guard being strict.
    """
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for offer in offers:
        item = offer["item"]
        if item["category"] != intent.category:
            continue
        price = offer["total"]["minor_units"]
        if intent.max_minor_units is not None and price > intent.max_minor_units:
            continue
        haystack = fold(f"{item['title']} {item['sku']}")
        score = sum(1 for keyword in set(intent.keywords) if keyword in haystack)
        if intent.keywords and score == 0:
            continue
        matches.append((score, price, offer))
    if not matches:
        return None
    # The words the person used win over the price. Asking for *the executive one* and
    # being handed the cheapest seat is the agent deciding it knows better — and it
    # would also hide the refusal the ceiling is there to produce.
    best_score = max(score for score, _, _ in matches)
    return min(
        (entry for entry in matches if entry[0] == best_score), key=lambda entry: entry[1]
    )[2]


class PurchasingAgent:
    def __init__(self, runtime: AvalRuntime, *, custody: KeyCustodyService, kid: str) -> None:
        self._runtime = runtime
        self._custody = custody
        self._kid = kid

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

    def _mandate_context(self, mandate_id: str) -> dict[str, Any] | None:
        snapshot = self._runtime.core.snapshot(mandate_id)
        if snapshot is None:
            return None
        mandate = snapshot.mandate
        return {
            "categories": sorted(mandate.allowed_categories),
            "merchants": sorted(mandate.allowed_merchant_ids),
            "remaining": snapshot.remaining.minor_units,
            "currency": snapshot.limit.currency,
            "scale": snapshot.limit.scale,
            "ceiling": None if mandate.ceiling is None else mandate.ceiling.minor_units,
        }

    def _propose(
        self, offers: list[dict[str, Any]], intent: PurchaseIntent, *, mandate_id: str, instruction: str
    ) -> tuple[dict[str, Any] | None, Proposal | None]:
        """The model picks from a shortlist, or the rules pick alone.

        Both halves are always available. If the model is unreachable, slow, or answers
        with nonsense, the deterministic reader decides and the purchase still happens —
        which is why this can be demonstrated on a hotel network.
        """
        if configured():
            candidates = shortlist(offers, intent)
            proposal = propose(instruction, candidates, mandate=self._mandate_context(mandate_id))
            if proposal is not None:
                chosen = next(
                    (offer for offer in candidates if offer["item"]["sku"] == proposal.sku), None
                )
                if chosen is not None:
                    return chosen, proposal
        return choose_offer(offers, intent), None

    def run(self, *, mandate_id: str, instruction: str) -> AgentRun:
        intent = parse_intent(instruction)
        offers = self._runtime.offers.catalog()
        offer, proposal = self._propose(
            offers, intent, mandate_id=mandate_id, instruction=instruction
        )
        chosen_by = "llm" if proposal is not None else "rules"
        rationale = None if proposal is None else (proposal.rationale or None)
        alternatives = () if proposal is None else proposal.alternatives
        if offer is None:
            return AgentRun(
                outcome="no_offer",
                reason_code="no_offer_matched",
                human_summary="Nenhuma oferta do catálogo atende ao pedido.",
                considered=len(offers),
                proposed_by=chosen_by,
            )

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
                proposed_by=chosen_by,
                rationale=rationale,
                alternatives=alternatives,
            )

        capture_body = {**purchase, "idempotency_key": f"cap_{checkout_id}"}
        agent = self._signed_call("/capture", capture_body)
        result = capture_purchase(
            self._runtime, agent=agent, body=CaptureRequest(**capture_body)
        )
        return AgentRun(
            outcome="settled" if result.approved else "refused",
            reason_code=result.reason_code,
            human_summary=(
                f"Compra de {offer['item']['title']} concluída."
                if result.approved
                else "Compra não concluída."
            ),
            offer=offer,
            reservation_id=None if result.reservation is None else result.reservation.id,
            settlement_reference=result.settlement_reference,
            authorization_proof=result.authorization_proof,
            escalation_id=result.escalation_id,
            considered=len(offers),
            proposed_by=chosen_by,
            rationale=rationale,
            alternatives=alternatives,
        )

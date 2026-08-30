"""The demo payment processor.

It stands where a real acquirer would, and it is deliberately hard to please:

- it refuses anything that is not a committed reservation;
- it verifies the authorization proof before moving money, so a settlement cannot
  happen without the token AVAL issued at the commit point;
- its reference is derived from the reservation, so the same purchase settles to the
  same reference twice and a replay is visible.

On top of that it carries the one knob an operator may turn, because the failure story
has to be demonstrated rather than described. The mode is read on every call and never
cached: a judge who flips it expects the very next purchase to behave differently.

The core never learns which processor this is. It sees a `SettlementAdapter`, calls it
after the commit point, and treats an exception as *unknown*, never as *declined*.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from aval.application.authorization_core import SettlementResult
from aval.domain.entities import Reservation
from aval.domain.enums import ReservationStatus

MODES = ("online", "offline", "decline")


class PspUnreachable(RuntimeError):
    """The processor did not answer. This is not a decline and must never be read as one."""


@dataclass
class PspControl:
    """The one mutable knob in the system, and it belongs to the operator."""

    mode: str = "online"


class DemoPspAdapter:
    def __init__(
        self,
        mode_provider: Callable[[], str] | None = None,
        *,
        proof_verifier: Callable[[str, Reservation], object] | None = None,
    ) -> None:
        self._mode_provider = mode_provider or (lambda: "online")
        self._proof_verifier = proof_verifier
        self._setup_sessions: dict[str, str] = {}

    def authorize(self, reservation: Reservation, proof: str) -> SettlementResult:
        mode = self._mode_provider()
        if mode == "offline":
            raise PspUnreachable("the processor did not answer")
        if mode == "decline":
            return SettlementResult(approved=False)
        # Money only moves for a reservation the core already committed.
        if reservation.status is not ReservationStatus.COMMITTED or not reservation.transaction_hash:
            return SettlementResult(approved=False)
        if self._proof_verifier is not None:
            try:
                self._proof_verifier(proof, reservation)
            except ValueError:
                return SettlementResult(approved=False)
        # Derived, not random: the same committed purchase always settles to the same
        # reference, so a duplicate settlement is recognisable rather than invisible.
        digest = hashlib.sha256(
            f"{reservation.id}:{reservation.transaction_hash}".encode("utf-8")
        ).hexdigest()[:24]
        return SettlementResult(approved=True, reference=f"psp_mock_{digest}")

    def refund(self, reservation: Reservation) -> SettlementResult:
        """Undo a charge, under the same knob as everything else.

        The modes mean here what they mean everywhere: `offline` raises, because a
        processor that did not answer has not refunded anything and the money must stay
        exactly where it is; `decline` refuses, because a refusal to refund is a real
        answer a real acquirer gives. Only the third case moves money back.
        """
        mode = self._mode_provider()
        if mode == "offline":
            raise PspUnreachable("the processor did not answer the reversal")
        if mode == "decline":
            return SettlementResult(approved=False)
        digest = hashlib.sha256(f"refund:{reservation.id}".encode("utf-8")).hexdigest()[:24]
        return SettlementResult(approved=True, reference=f"psp_refund_{digest}")

    # ── card registration ──────────────────────────────────────────────────
    #
    # The same two calls Stripe answers, so every surface registers a card the one way:
    # ask the processor for a page, come back with a token. Without these the offline
    # demo had no card at all — and a mandate that names no payment method is refused
    # at capture, so the default configuration could not complete a purchase through
    # any interface. A demo processor with no card form is not a simpler processor,
    # it is a processor nobody can pay with.
    #
    # There is no page and no number: the form is imaginary and the card is a fiction
    # the processor mints. What is preserved is the property that matters — the token
    # comes from the processor and the caller never names it, so nothing upstream can
    # attach a credential its holder never registered.

    def create_setup_session(self, mandate_id: str, *, return_url: str) -> dict[str, str]:
        if self._mode_provider() == "offline":
            raise PspUnreachable("the processor did not answer")
        session_id = "cs_demo_" + hashlib.sha256(mandate_id.encode("utf-8")).hexdigest()[:16]
        # ponytail: in memory, so a restart forgets the open sessions. The card itself
        # is on the mandate by then; a forgotten session just means opening a new one.
        self._setup_sessions[session_id] = mandate_id
        return {"session_id": session_id, "url": f"{return_url}?demo_session={session_id}"}

    def read_setup_session(self, session_id: str, *, mandate_id: str) -> dict[str, str] | None:
        """The card, or None for a session this mandate did not open.

        The same refusal the Stripe adapter makes, and it carries more weight here:
        this session id is derived from the mandate rather than minted at random, so
        it is the *only* thing standing between a guessed id and somebody else's card.
        The endpoints above it are holder-signed for that reason — a processor's
        session id was never an entitlement, and this one is not even a secret.
        """
        if self._setup_sessions.get(session_id) != mandate_id:
            return None
        return {"token": f"vt_demo_{session_id.removeprefix('cs_demo_')}", "label": "•••• 4242"}

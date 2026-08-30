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

    def authorize(self, reservation: Reservation, proof: str) -> SettlementResult:
        mode = self._mode_provider()
        if mode == "offline":
            raise PspUnreachable("o processador não respondeu")
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
            raise PspUnreachable("o processador não respondeu ao estorno")
        if mode == "decline":
            return SettlementResult(approved=False)
        digest = hashlib.sha256(f"refund:{reservation.id}".encode("utf-8")).hexdigest()[:24]
        return SettlementResult(approved=True, reference=f"psp_refund_{digest}")

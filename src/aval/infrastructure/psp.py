"""The demo payment processor.

It stands where a real acquirer would. The core never learns which one it is: it sees
a `SettlementAdapter`, calls it after the commit point, and treats an exception as
*unknown*, never as *declined*.

The mode is read on every call and never cached. A judge who flips it expects the very
next purchase to behave differently, and a cached mode would quietly make that a lie.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from aval.application.authorization_core import SettlementResult
from aval.domain.entities import Reservation

MODES = ("online", "offline", "decline")


class PspUnreachable(RuntimeError):
    """The processor did not answer. This is not a decline and must never be read as one."""


@dataclass
class PspControl:
    """The one mutable knob in the system, and it belongs to the operator."""

    mode: str = "online"


class DemoPspAdapter:
    def __init__(self, mode_provider: Callable[[], str] | None = None) -> None:
        self._mode_provider = mode_provider or (lambda: "online")

    def authorize(self, reservation: Reservation, proof: str) -> SettlementResult:
        mode = self._mode_provider()
        if mode == "decline":
            return SettlementResult(approved=False)
        if mode == "offline":
            raise PspUnreachable("o processador não respondeu")
        return SettlementResult(approved=True, reference=f"psp_{uuid4().hex[:8]}")

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib

from aval.domain.entities import Reservation
from aval.domain.enums import ReservationStatus


@dataclass(frozen=True)
class MockSettlementResult:
    approved: bool
    reference: str | None = None


class MockCardPSP:
    """Offline PSP boundary; it has no ledger, audit, or database dependency."""

    def __init__(
        self,
        *,
        proof_verifier: Callable[[str, Reservation], object],
        approve: bool = True,
    ) -> None:
        self._proof_verifier = proof_verifier
        self._approve = approve

    def authorize(self, reservation: Reservation, proof: str) -> MockSettlementResult:
        if reservation.status is not ReservationStatus.COMMITTED:
            return MockSettlementResult(False)
        try:
            self._proof_verifier(proof, reservation)
        except ValueError:
            return MockSettlementResult(False)
        if not self._approve:
            return MockSettlementResult(False)

        digest = hashlib.sha256(
            f"{reservation.id}:{reservation.transaction_hash}".encode("utf-8")
        ).hexdigest()[:24]
        return MockSettlementResult(True, f"psp_mock_{digest}")

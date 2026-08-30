from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta


class ClockService:
    """Single injectable clock for all authorization-time validity decisions.

    The demo offset lets a judge watch a mandate expire instead of waiting for the end
    of the month. It is **monotonic on purpose**: advancing only ever takes authority
    away, while rewinding would un-expire a mandate — an operator handing back spending
    authority that the holder's own validity had already ended. That is the holder's
    key's job, never a token's, so `advance` refuses anything but a step forward.
    """

    def __init__(self, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._offset = timedelta(0)

    def now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now + self._offset

    @property
    def offset(self) -> timedelta:
        return self._offset

    def advance(self, delta: timedelta) -> timedelta:
        """Move the demo clock forward. Returns the accumulated offset."""
        if delta <= timedelta(0):
            raise ValueError("clock moves forward only")
        self._offset = self._offset + delta
        return self._offset

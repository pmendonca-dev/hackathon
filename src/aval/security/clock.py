from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime


class ClockService:
    """Single injectable clock for all authorization-time validity decisions."""

    def __init__(self, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now

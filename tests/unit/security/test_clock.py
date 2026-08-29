from __future__ import annotations

from datetime import UTC, datetime

from aval.security.clock import ClockService


def test_clock_service_returns_the_injected_time_for_deterministic_checks():
    frozen = datetime(2026, 8, 29, 12, 30, tzinfo=UTC)

    clock = ClockService(now_provider=lambda: frozen)

    assert clock.now() == frozen

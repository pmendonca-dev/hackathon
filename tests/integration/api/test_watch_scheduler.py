"""A standing order fires with nobody at the keyboard — and still obeys the mandate.

Two things are asserted, and the second matters more than the first. The scheduler must
actually act, because until it existed a watch only fired while the Telegram bot's
polling loop happened to be running. And it must carry no authority of its own: firing
means asking the core, so a watch against a revoked mandate is refused exactly like a
purchase somebody typed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from aval.agent.scheduler import (
    MINIMUM_INTERVAL_SECONDS,
    configured_tick_interval,
    tick_once,
)
from aval.agent.purchasing_agent import PurchasingAgent
from aval.agent.watches import WatchService
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole, WatchStatus
from aval.domain.money import Money
from aval.runtime import build_runtime
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


@pytest.fixture
def runtime(tmp_path):
    return build_runtime(database_path=tmp_path / "watches.sqlite3")


@pytest.fixture
def holder() -> KeyCustodyService:
    custody = KeyCustodyService()
    custody.generate_es256("holder-k1")
    return custody


def _mandate(runtime, holder: KeyCustodyService, mandate_id: str) -> str:
    runtime.core.register_mandate(
        Mandate(
            id=mandate_id,
            principal=Principal("usr_marta", "Marta"),
            allowed_merchant_ids=frozenset({"vuelaya"}),
            allowed_categories=frozenset({"travel"}),
            limit=Money(100_000, "USD", 2),
            ceiling=Money(90_000, "USD", 2),
            expires_at=runtime.clock.now() + timedelta(days=7),
            policy_version=1,
            revocation_metadata={"revocation_id": f"rev_{mandate_id}", "epoch": 0},
            authorities=(
                RevocationAuthority(
                    f"auth_{mandate_id}",
                    "holder-k1",
                    RevocationRole.HOLDER,
                    holder.public_jwk("holder-k1"),
                    frozenset({"mandate"}),
                ),
            ),
        )
    )
    return mandate_id


def _watch(runtime, mandate_id: str, instruction: str):
    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    return service.register(mandate_id=mandate_id, instruction=instruction)


def test_the_interval_is_off_unless_the_deployment_asks_for_one(monkeypatch) -> None:
    monkeypatch.delenv("AVAL_WATCH_TICK_SECONDS", raising=False)
    assert configured_tick_interval() is None

    monkeypatch.setenv("AVAL_WATCH_TICK_SECONDS", "30")
    assert configured_tick_interval() == 30.0

    # A number too small is a busy-wait against the catalogue, not a schedule.
    monkeypatch.setenv("AVAL_WATCH_TICK_SECONDS", "0.1")
    assert configured_tick_interval() == MINIMUM_INTERVAL_SECONDS

    # Nonsense turns the loop off rather than crashing the server on boot.
    monkeypatch.setenv("AVAL_WATCH_TICK_SECONDS", "sempre")
    assert configured_tick_interval() is None


def test_a_tick_with_no_watches_does_nothing(runtime) -> None:
    assert tick_once(runtime) == 0


def test_a_watch_fires_without_anyone_asking(runtime, holder) -> None:
    """The premise of the case: the agent acts, and nobody pressed anything."""
    mandate_id = _mandate(runtime, holder, "mandate_watch_fires")
    watch = _watch(runtime, mandate_id, "compre um voo para Córdoba")

    fired = tick_once(runtime)

    assert fired == 1
    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    closed = next(item for item in service.for_mandate(mandate_id) if item.id == watch.id)
    assert closed.status is WatchStatus.FIRED


def test_a_watch_against_a_revoked_mandate_is_refused_like_any_purchase(runtime, holder) -> None:
    """The scheduler carries no authority. Firing asks the core, and the core says no."""
    mandate_id = _mandate(runtime, holder, "mandate_watch_revoked")
    _watch(runtime, mandate_id, "compre um voo para Córdoba")
    runtime.core.submit_signed_revocation(
        sign_compact_jws(
            {
                "mandate_id": mandate_id,
                "scope": "mandate",
                "reason": "revogado pelo titular",
                "epoch": 1,
            },
            holder,
            "holder-k1",
        )
    )

    tick_once(runtime)

    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    closed = service.for_mandate(mandate_id)[0]
    assert closed.outcome == "mandate_revoked"
    assert closed.settlement_reference is None


def test_one_broken_mandate_does_not_stop_the_others(runtime, holder, monkeypatch) -> None:
    """A tick is a loop over independent mandates, not a transaction across them."""
    first = _mandate(runtime, holder, "mandate_watch_a")
    second = _mandate(runtime, holder, "mandate_watch_b")
    _watch(runtime, first, "compre um voo para Córdoba")
    _watch(runtime, second, "compre um voo para Córdoba")

    original = WatchService.tick

    def explode_on_the_first(self, mandate_id: str):
        if mandate_id == first:
            raise RuntimeError("o catálogo caiu para este mandato")
        return original(self, mandate_id)

    monkeypatch.setattr(WatchService, "tick", explode_on_the_first)

    assert tick_once(runtime) == 1

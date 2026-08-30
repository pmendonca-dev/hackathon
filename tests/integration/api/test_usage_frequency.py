"""Mandates with a frequency condition — the case's "up to 3 times a month".

Frequency is authority, not preference: it says how often the agent may act, the same
way the budget says how much. So it lives in the core, on the same ladder, and it is
*approvable* — a human can say yes to a fourth purchase, exactly as they can to one
over budget. The ceiling stays the only bound with no approval path.

A use is burned by money actually being held, so a reservation the processor released
does not consume one. A declined card that silently ate a monthly allowance would be a
frequency limit that punishes the buyer for the processor's answer.
"""

from __future__ import annotations

from typing import Any

from tests.integration.api.conftest import Harness

MONTH_SECONDS = 30 * 24 * 3600


def limited(harness: Harness, *, max_uses: int = 3, window: int = MONTH_SECONDS) -> str:
    return harness.create_mandate(
        usage_limit={"max_uses": max_uses, "window_seconds": window},
        limit={"minor_units": 100000, "currency": "USD", "scale": 2},
        ceiling={"minor_units": 50000, "currency": "USD", "scale": 2},
    )


def buy(harness: Harness, mandate_id: str, tag: str) -> dict[str, Any]:
    body = harness.purchase(
        mandate_id,
        checkout_id=f"chk_{tag}",
        total={"minor_units": 1000, "currency": "USD", "scale": 2},
        idempotency_key=f"cap_{tag}",
    )
    return harness.capture(body).json()


def test_a_mandate_without_a_usage_limit_is_unaffected(harness: Harness) -> None:
    mandate_id = harness.create_mandate(
        limit={"minor_units": 100000, "currency": "USD", "scale": 2}
    )

    for index in range(5):
        assert buy(harness, mandate_id, f"free{index}")["approved"] is True


def test_the_fourth_purchase_inside_the_window_escalates(harness: Harness) -> None:
    mandate_id = limited(harness)
    for index in range(3):
        assert buy(harness, mandate_id, f"ok{index}")["approved"] is True

    fourth = buy(harness, mandate_id, "fourth")

    assert fourth["approved"] is False
    assert fourth["reason_code"] == "usage_limit_exceeded"
    # Approvable, like the budget. A human may still say yes to this one.
    assert fourth["escalation_id"] is not None


def test_a_use_that_fell_out_of_the_window_does_not_count(harness: Harness) -> None:
    mandate_id = limited(harness, max_uses=2, window=3600)
    for index in range(2):
        assert buy(harness, mandate_id, f"early{index}")["approved"] is True
    assert buy(harness, mandate_id, "blocked")["reason_code"] == "usage_limit_exceeded"

    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 7200}
    )

    assert buy(harness, mandate_id, "later")["approved"] is True


def test_a_released_reservation_does_not_burn_a_use(harness: Harness) -> None:
    """The processor declining is not the buyer spending their monthly allowance."""
    mandate_id = limited(harness, max_uses=2)
    assert buy(harness, mandate_id, "held")["approved"] is True
    harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "decline"})
    assert buy(harness, mandate_id, "declined")["approved"] is False
    harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "online"})

    second = buy(harness, mandate_id, "second")

    assert second["approved"] is True, second


def test_the_ladder_shows_the_usage_check_and_what_it_counted(harness: Harness) -> None:
    mandate_id = limited(harness, max_uses=1)
    buy(harness, mandate_id, "first")

    response = harness.authorize(
        harness.purchase(
            mandate_id,
            checkout_id="chk_trace",
            total={"minor_units": 1000, "currency": "USD", "scale": 2},
        )
    )

    trace = response.json()["evaluation_trace"]
    assert trace[-1] == {
        "check": "within_usage_window",
        "passed": False,
        "detail": "1 uso em 2592000s atinge o máximo de 1",
    }


def test_a_mandate_without_the_condition_never_shows_the_usage_rung(
    harness: Harness,
) -> None:
    """An absent condition is absent from the ladder, not a rung that trivially passes."""
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id))

    assert "within_usage_window" not in [
        step["check"] for step in response.json()["evaluation_trace"]
    ]


def test_the_usage_limit_is_visible_on_the_mandate(harness: Harness) -> None:
    mandate_id = limited(harness, max_uses=3)
    buy(harness, mandate_id, "one")

    view = harness.read_mandate(mandate_id).json()

    assert view["usage_limit"] == {"max_uses": 3, "window_seconds": MONTH_SECONDS}
    assert view["uses_in_window"] == 1


def test_a_usage_limit_must_be_positive(harness: Harness) -> None:
    response = harness.client.post(
        "/mandates",
        json=harness.mandate_payload(usage_limit={"max_uses": 0, "window_seconds": 3600}),
    )

    assert response.status_code == 422, response.text

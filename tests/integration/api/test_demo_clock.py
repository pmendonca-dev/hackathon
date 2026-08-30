"""The demo clock, and the one direction it may not turn.

A mandate's validity is read against a single injected clock. Without a way to move it,
"the mandate expires" is the one trial-by-fire action a judge cannot perform — they
would have to wait until the end of the month, or the team would have to recreate the
mandate for them, which is exactly the "team touches something" the case forbids.

Moving time **forward** only ever removes authority: mandates expire, nothing is
granted. Moving it **backward** would un-expire a mandate, and that is an operator
handing back spending authority the holder's own validity had already taken away. The
clock is therefore monotonic, and `test_the_clock_refuses_to_run_backwards` is the
test that keeps an operator out of the holder's job.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness


def test_advancing_the_clock_expires_a_mandate_that_was_valid(harness: Harness) -> None:
    mandate_id = harness.create_mandate(expires_at="2026-08-29T18:00:00Z")
    assert harness.authorize(harness.purchase(mandate_id)).json()["decision"] == "authorized"

    moved = harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 8 * 3600}
    )

    assert moved.status_code == 200, moved.text
    decision = harness.authorize(harness.purchase(mandate_id, checkout_id="chk_after")).json()
    assert decision["reason_code"] == "mandate_expired"


def test_the_clock_refuses_to_run_backwards(harness: Harness) -> None:
    """An operator who could rewind time could revive an expired mandate — that is
    granting spending authority, and it belongs to the holder's key, not to a token."""
    mandate_id = harness.create_mandate(expires_at="2026-08-29T18:00:00Z")
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 8 * 3600}
    )

    rewound = harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": -8 * 3600}
    )

    assert rewound.status_code == 422, rewound.text
    assert rewound.json()["reason_code"] == "clock_moves_forward_only"
    still_expired = harness.authorize(harness.purchase(mandate_id, checkout_id="chk_x")).json()
    assert still_expired["reason_code"] == "mandate_expired"


def test_a_zero_advance_is_refused_as_well(harness: Harness) -> None:
    response = harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 0}
    )

    assert response.status_code == 422, response.text


def test_moving_the_clock_requires_the_operator_token(harness: Harness) -> None:
    response = harness.client.post("/admin/clock", json={"advance_seconds": 60})

    assert response.status_code == 401, response.text
    assert response.json()["reason_code"] == "operator_token_missing"


def test_reading_the_clock_reports_the_accumulated_offset(harness: Harness) -> None:
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 120}
    )
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 60}
    )

    response = harness.client.get("/admin/clock", headers=harness.operator)

    assert response.status_code == 200, response.text
    assert response.json()["offset_seconds"] == 180
    assert response.json()["now"].startswith("2026-08-29T12:03:00")


def test_the_clock_the_ledger_writes_with_moves_too(harness: Harness) -> None:
    """One clock, not two. A trail stamped from a different source than the decision
    would let an auditor read an ordering that never happened."""
    mandate_id = harness.create_mandate()
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 3600}
    )

    harness.authorize(harness.purchase(mandate_id))

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    assert entries[-1]["occurred_at"].startswith("2026-08-29T13:00:00")


def test_health_publishes_the_instant_mandates_are_read_against(harness: Harness) -> None:
    """The mandate form needs the server's `now`, not the browser's.

    A judge who advances the clock a month and then creates a mandate with a date the
    browser computed from its own wall clock gets a mandate that is already expired —
    and every creation after that is a 422 nobody asked for. The public health probe is
    where the page reads the instant its dates have to beat. It is not a secret: the
    trial-by-fire console already shows the offset, and a clock the judge moved is a
    clock the judge knows about.
    """
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 3600}
    )

    body = harness.client.get("/health").json()

    assert body["status"] == "ok"
    assert body["now"].startswith("2026-08-29T13:00:00")

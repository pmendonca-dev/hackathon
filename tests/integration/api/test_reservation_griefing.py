"""Denial of service from inside the mandate.

Every other refusal in this system answers "you may not spend this". This one answers
a different attack: an agent that never spends anything and still leaves the buyer
unable to buy. Each capture the processor does not answer holds budget and holds it
correctly — so an agent with a bug, or a hostile one, repeats the call until 100% of
the mandate is reserved. Zero money moves, no reason code fires, and Marta simply
cannot purchase any more.

The processor switch on the judge's console is what makes this reachable in a demo,
which is exactly why it has to be closed.
"""

from __future__ import annotations

from aval.security.jws import sign_compact_jws


def set_psp(harness, mode: str):
    response = harness.client.post("/admin/psp", headers=harness.operator, json={"mode": mode})
    assert response.status_code == 200, response.text


def roomy_mandate(harness) -> str:
    """A budget wide enough that the budget is not what refuses.

    With the default limit the second purchase already exceeds it, and the griefing is
    invisible behind `budget_exceeded` — which is the reason this hole survived: the
    attack only shows up on a mandate rich enough to be worth freezing.
    """
    return harness.create_mandate(limit={"minor_units": 100000, "currency": "USD", "scale": 2})


def hold(harness, mandate_id: str, n: int):
    """Leave `n` reservations live: committed, unanswered, budget held."""
    return harness.capture(
        harness.purchase(mandate_id, checkout_id=f"chk_hold_{n}")
        | {"idempotency_key": f"cap_hold_{n}"}
    )


def test_an_agent_cannot_freeze_the_budget_with_unanswered_captures(harness):
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)

    fourth = hold(harness, mandate_id, 3)

    assert fourth.json()["reason_code"] == "reservation_limit"


def test_the_reservation_limit_is_a_refusal_and_never_an_approval_request(harness):
    """A human saying yes does not un-stick money that is already stuck. There is no
    handle to sign, so there must be no button to press."""
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)

    fourth = hold(harness, mandate_id, 3)

    assert fourth.json()["approved"] is False
    assert fourth.json().get("escalation_id") is None


def test_reconciling_gives_the_reservation_slots_back(harness):
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)
    assert hold(harness, mandate_id, 3).json()["reason_code"] == "reservation_limit"

    set_psp(harness, "decline")
    harness.client.post("/reconcile", headers=harness.operator)

    set_psp(harness, "online")
    assert hold(harness, mandate_id, 4).json()["approved"] is True


def test_a_purchase_the_processor_answered_holds_no_slot(harness):
    """Only unresolved reservations occupy a slot. A settled purchase is finished."""
    mandate_id = harness.create_mandate(
        limit={"minor_units": 500000, "currency": "USD", "scale": 2}
    )

    for n in range(5):
        assert hold(harness, mandate_id, n).json()["approved"] is True


def test_the_ladder_stops_at_the_slot_and_never_reads_the_budget(harness):
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)

    preview = harness.authorize(harness.purchase(mandate_id, checkout_id="chk_preview"))

    trace = preview.json()["evaluation_trace"]
    assert trace[-1]["check"] == "reservation_slot_free"
    assert trace[-1]["passed"] is False
    assert not any(step["check"] == "within_budget" for step in trace)


def test_the_ceiling_still_answers_before_the_slot_does(harness):
    """Ordering is the rule. An amount nobody may spend is refused for being that,
    not for arriving while the slots happened to be full."""
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)

    over_ceiling = harness.capture(
        harness.purchase(
            mandate_id,
            checkout_id="chk_big",
            total={"minor_units": 90000, "currency": "USD", "scale": 2},
        )
        | {"idempotency_key": "cap_big"}
    )

    assert over_ceiling.json()["reason_code"] == "mandate_ceiling"


def test_a_revoked_mandate_still_answers_revoked_with_the_slots_full(harness):
    """Authority before operations, the same way authority comes before money."""
    mandate_id = roomy_mandate(harness)
    set_psp(harness, "offline")
    for n in range(3):
        hold(harness, mandate_id, n)
    harness.client.post(
        f"/mandates/{mandate_id}/revocation",
        json={
            "token": sign_compact_jws(
                {
                    "mandate_id": mandate_id,
                    "scope": "mandate",
                    "reason": "holder_request",
                    "epoch": 1,
                },
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    blocked = hold(harness, mandate_id, 3)

    assert blocked.json()["reason_code"] == "mandate_revoked"

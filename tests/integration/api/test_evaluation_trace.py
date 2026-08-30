"""The ladder the core walked, not just where it stopped.

`AuthorizationCore` evaluates in a fixed order, and the order *is* the rule: authority
before money. Returning only the first failing reason makes that order invisible — the
caller sees `budget_exceeded` and has no way to know that revocation was checked first.
The trace publishes the ladder so the property can be read instead of trusted.

It carries limits and spend, so it belongs to the human and the auditor. The merchant
never receives it, and the last test here is what enforces that.
"""

from __future__ import annotations

from tests.integration.api.conftest import Harness
from aval.security.jws import sign_compact_jws


def steps_of(response) -> list[dict]:
    return response.json()["evaluation_trace"]


def names_of(response) -> list[str]:
    return [step["check"] for step in steps_of(response)]


def test_an_authorized_purchase_publishes_every_check_it_passed(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id))

    assert response.json()["decision"] == "authorized"
    assert all(step["passed"] for step in steps_of(response))
    assert names_of(response) == [
        "mandate_exists",
        "revocation_readable",
        "mandate_not_revoked",
        "merchant_not_revoked",
        # The mandate now names a card, so the ladder has a rung for it: a cancelled
        # instrument stops the purchase before any money check is consulted.
        "instrument_not_revoked",
        "budget_not_zeroed",
        "mandate_not_expired",
        "merchant_in_scope",
        "category_in_scope",
        "money_unit_matches",
        "amount_positive",
        "below_ceiling",
        # Between the ceiling and the money: an operational guard against an agent
        # that holds budget without spending it. See `test_reservation_griefing.py`.
        "reservation_slot_free",
        "within_budget",
    ]


def test_a_refused_purchase_stops_the_trace_at_the_check_that_failed(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = harness.authorize(
        harness.purchase(
            mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}
        )
    )

    assert response.json()["reason_code"] == "mandate_ceiling"
    trace = steps_of(response)
    assert trace[-1] == {
        "check": "below_ceiling",
        "passed": False,
        "detail": "amount 90000 above the ceiling 50000",
    }
    # The ladder stops where it failed; it does not report checks it never ran.
    assert "within_budget" not in names_of(response)


def test_the_trace_names_the_numbers_that_were_compared(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = harness.authorize(
        harness.purchase(
            mandate_id, total={"minor_units": 30000, "currency": "USD", "scale": 2}
        )
    )

    assert response.json()["reason_code"] == "budget_exceeded"
    failed = [step for step in steps_of(response) if not step["passed"]]
    assert failed[0]["detail"] == "spent 0 + 30000 exceeds the limit 20000"


def test_a_revoked_mandate_stops_the_ladder_before_any_money_check(harness: Harness) -> None:
    """Authority before money, published. A revocation is never reachable by being
    cheap enough, and the trace is what makes that visible rather than asserted."""
    mandate_id = harness.create_mandate()
    harness.client.post(
        f"/mandates/{mandate_id}/revocation",
        json={
            "token": sign_compact_jws(
                {"mandate_id": mandate_id, "scope": "mandate", "reason": "trace", "epoch": 1},
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    response = harness.authorize(harness.purchase(mandate_id))

    assert response.json()["reason_code"] == "mandate_revoked"
    walked = names_of(response)
    assert walked[-1] == "mandate_not_revoked"
    for money_check in ("below_ceiling", "within_budget", "amount_positive"):
        assert money_check not in walked


def test_an_unknown_mandate_traces_only_the_check_it_could_run(harness: Harness) -> None:
    response = harness.authorize(harness.purchase("mandate_nonexistent"))

    assert names_of(response) == ["mandate_exists"]
    assert steps_of(response)[0]["passed"] is False


def test_the_agent_purchase_publishes_the_ladder_its_attempt_ran_into(
    harness: Harness,
) -> None:
    """The free-text surface is where a judge attacks the mandate. Showing the ladder
    is what turns a refusal into an explanation of *which* authority stopped it."""
    mandate_id = harness.create_mandate()

    response = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "buy the business class ticket to Córdoba"},
    )

    body = response.json()
    assert body["reason_code"] == "mandate_ceiling"
    assert body["evaluation_trace"][-1]["check"] == "below_ceiling"
    assert body["evaluation_trace"][-1]["passed"] is False


def test_a_settled_agent_purchase_still_carries_the_full_ladder(harness: Harness) -> None:
    mandate_id = harness.create_mandate()

    response = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    )

    body = response.json()
    assert body["outcome"] == "settled", body
    assert [step["check"] for step in body["evaluation_trace"]][-1] == "within_budget"
    assert all(step["passed"] for step in body["evaluation_trace"])


def test_the_merchant_verification_never_carries_the_evaluation_trace(
    harness: Harness,
) -> None:
    """The trace names the limit, the ceiling and the spend. A merchant that learned
    those would learn the buyer's budget from a receipt it is entitled to check."""
    mandate_id = harness.create_mandate()
    offers = harness.client.get("/merchant/offers").json()["offers"]
    offer = next(item for item in offers if item["item"]["sku"] == "FL-SAO-COR-0917")
    settled = harness.capture(harness.purchase_from_offer(mandate_id, offer, "cap_trace"))

    response = harness.client.post(
        "/merchant/verify",
        json={
            "authorization_proof": settled.json()["authorization_proof"],
            "merchant_authorization": offer["merchant_authorization"],
        },
    )

    assert response.json()["accepted"] is True
    assert "evaluation_trace" not in response.text
    assert "below_ceiling" not in response.text
    assert "within_budget" not in response.text

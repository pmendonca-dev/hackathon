"""The third payment state: authorized, in confirmation, settled.

A processor that never answers is not a refusal and is not a success. Today the
budget was already held correctly, but the trail said nothing between the commit and
the settlement — so the only thing a person saw was a 502, which reads as a bug.

An honest system shows the uncertainty instead of hiding it.
"""

from __future__ import annotations


def buy(harness, mandate_id: str, key: str = "cap_doubt"):
    return harness.capture(harness.purchase(mandate_id) | {"idempotency_key": key})


def set_psp(harness, mode: str):
    response = harness.client.post("/admin/psp", headers=harness.operator, json={"mode": mode})
    assert response.status_code == 200, response.text


def human_entries(harness, mandate_id: str):
    return harness.human_ledger(mandate_id).json()["entries"]


def test_a_processor_that_never_answers_leaves_the_purchase_in_confirmation(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    buy(harness, mandate_id)

    last = human_entries(harness, mandate_id)[-1]
    assert last["event_type"] == "payment_in_doubt"
    assert last["detail"]["payment_state"] == "in_doubt"


def test_the_person_reads_confirmation_and_never_the_word_approved(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    buy(harness, mandate_id)

    last = human_entries(harness, mandate_id)[-1]
    assert "confirmação" in last["human_summary"].lower()
    assert "liquidado" not in last["human_summary"].lower()


def test_a_purchase_in_confirmation_never_reports_a_settlement_reference(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    buy(harness, mandate_id)

    entries = human_entries(harness, mandate_id)
    assert not any(entry["event_type"] == "purchase_settled" for entry in entries)
    assert all(entry["detail"].get("settlement_reference") is None for entry in entries)


def test_the_budget_stays_held_while_the_payment_is_in_doubt(harness):
    """The state is new; the money rule is the one that was already right."""
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    response = buy(harness, mandate_id)

    assert response.status_code == 502
    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] == 13000


def test_reconciling_moves_the_purchase_out_of_confirmation(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)

    set_psp(harness, "online")
    reconciled = harness.client.post("/reconcile", headers=harness.operator)

    assert reconciled.json()["settled"] == 1
    last = human_entries(harness, mandate_id)[-1]
    assert last["event_type"] == "purchase_settled"
    assert last["detail"]["payment_state"] == "settled"


def test_a_purchase_the_processor_answered_is_never_in_doubt(harness):
    mandate_id = harness.create_mandate()

    buy(harness, mandate_id)

    entries = human_entries(harness, mandate_id)
    assert not any(entry["event_type"] == "payment_in_doubt" for entry in entries)
    assert entries[-1]["detail"]["payment_state"] == "settled"


def test_a_declined_purchase_is_declined_and_not_in_doubt(harness):
    """Refused and unanswered are different facts, and the trail keeps them apart."""
    mandate_id = harness.create_mandate()
    set_psp(harness, "decline")

    buy(harness, mandate_id)

    last = human_entries(harness, mandate_id)[-1]
    assert last["event_type"] == "purchase_declined"
    assert last["detail"]["payment_state"] == "declined"


def test_the_trail_still_verifies_after_a_payment_lands_in_doubt(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)

    assert harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()["intact"]


def test_the_merchant_never_learns_a_payment_was_in_doubt(harness):
    """Uncertainty about the buyer's money is the buyer's business, not the seller's."""
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)

    entries = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    ).json()["entries"]

    assert not any(entry["event_type"] == "payment_in_doubt" for entry in entries)


def test_the_agent_reports_confirmation_instead_of_an_error(harness):
    """The route a person actually drives must not answer a held purchase with a 502.

    `/capture` is a machine contract and 502 is the right answer there — the caller has
    to know it got no answer. But the bot and the browser call `/agent/purchase`, and
    telling someone "erro 502" about a payment that may well have gone through is the
    exact lie this state exists to remove.
    """
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    response = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "in_doubt"


def test_the_agent_says_confirmation_and_never_says_bought(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    response = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    )

    summary = response.json()["human_summary"].lower()
    assert "confirmação" in summary
    assert "concluída" not in summary


def test_the_budget_the_agent_held_is_still_held(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    )

    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] > 0

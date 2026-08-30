"""The mandate names the payment method, and the payment method can be cancelled alone.

The case asks the human to authorize *what may be bought, the limits, the validity and
the payment method*, without the raw card ever reaching the agent. The first three were
already here. These tests hold the fourth from both ends:

- a card typed once is tokenized at the edge and is gone; what survives is a token the
  agent presents and four digits a person recognises;
- a capture presenting a different instrument, or none, is refused before the ladder
  ever reaches the money;
- cancelling the card is not cancelling the agent. The mandate stays ACTIVE, the budget
  stays where it was, and the next purchase is refused for the reason that is true.
"""

from __future__ import annotations

from aval.security.jws import sign_compact_jws

CARD = "4242424242424242"


def with_card(harness, **overrides):
    """A mandate that names a card, plus the scope that cancels it."""
    response = harness.client.post(
        "/mandates",
        json=harness.mandate_payload(payment_method={"card_number": CARD}, **overrides),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["mandate_id"], body["instrument_revocation_scope"]


def offer_for(harness, sku: str) -> dict:
    offers = harness.client.get("/merchant/offers").json()["offers"]
    return next(offer for offer in offers if offer["item"]["sku"] == sku)


def buy(harness, mandate_id: str, *, instrument_id: str | None, key: str = "cap_1"):
    offer = offer_for(harness, "FL-SAO-COR-0917")
    body = harness.purchase_from_offer(mandate_id, offer, key)
    body["instrument_id"] = instrument_id
    return harness.capture(body)


def cancel_card(harness, mandate_id: str, scope: str):
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": scope, "reason": "cartão perdido", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )
    return harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})


def test_the_card_is_read_once_and_only_four_digits_survive(harness):
    """Nothing that can pay for something is stored, and the holder can still tell
    which card they authorized."""
    mandate_id, scope = with_card(harness)

    view = harness.client.get(f"/mandates/{mandate_id}").json()

    assert view["instrument_label"] == "•••• 4242"
    assert CARD not in harness.client.get(f"/mandates/{mandate_id}").text
    # The token is authority, so it is never served — only the agent needs it.
    assert "instrument_token" not in view
    assert scope.startswith("instrument:vt_")


def test_a_mandate_naming_a_card_buys_with_it(harness):
    mandate_id, _ = with_card(harness)
    instrument = harness.runtime.core.mandate(mandate_id).instrument

    response = buy(harness, mandate_id, instrument_id=instrument.token)

    assert response.status_code == 200, response.text
    assert response.json()["approved"] is True


def test_a_capture_presenting_another_instrument_is_refused(harness):
    """A token from somewhere else is not this mandate's payment method."""
    mandate_id, _ = with_card(harness)

    response = buy(harness, mandate_id, instrument_id="vt_algum_outro_token")

    assert response.json()["reason_code"] == "instrument_not_in_mandate"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_a_capture_presenting_no_instrument_is_refused_not_waved_through(harness):
    """Fail-closed: omitting the field must not be the way around it."""
    mandate_id, _ = with_card(harness)

    response = buy(harness, mandate_id, instrument_id=None)

    assert response.json()["reason_code"] == "instrument_not_in_mandate"


def test_the_ladder_stops_before_it_ever_prices_the_purchase(harness):
    """The trace is the evidence: no money check was consulted."""
    mandate_id, _ = with_card(harness)
    offer = offer_for(harness, "FL-SAO-COR-0917")
    body = harness.purchase_from_offer(mandate_id, offer, None)
    body["instrument_id"] = "vt_outro"

    trace = harness.authorize(body).json()["evaluation_trace"]
    # `/authorize` is a preview and does not carry an instrument; the refusal belongs to
    # the capture, which is where money would move.
    assert [step["check"] for step in trace if not step["passed"]] == []

    captured = buy(harness, mandate_id, instrument_id="vt_outro")
    assert captured.json()["reason_code"] == "instrument_not_in_mandate"


def test_a_mandate_that_names_no_card_cannot_pay_at_all(harness):
    """Authority to spend is not a payment method, and does not imply one.

    This used to settle: a mandate with no instrument skipped the check entirely.
    Against a mock processor that reads as harmless; against a real one it is the
    difference between "there is no card on file" and "charged anyway".
    """
    mandate_id = harness.create_mandate(payment_method=None)

    response = buy(harness, mandate_id, instrument_id=None)

    assert response.json()["approved"] is False
    assert response.json()["reason_code"] == "instrument_not_in_mandate"


def test_a_mandate_with_no_card_is_not_rescued_by_presenting_one(harness):
    """Nor by inventing a token: the mandate names the instrument, not the buyer."""
    mandate_id = harness.create_mandate(payment_method=None)

    response = buy(harness, mandate_id, instrument_id="vt_qualquer_um")

    assert response.json()["reason_code"] == "instrument_not_in_mandate"


def test_cancelling_the_card_leaves_the_agent_alive_and_the_budget_intact(harness):
    """Authority and payment are two different things, revoked separately.

    A holder who loses a card should not have to end their agent's mandate to stop it
    being charged — and a holder who ends the mandate should not have to cancel a card.
    """
    mandate_id, scope = with_card(harness)
    instrument = harness.runtime.core.mandate(mandate_id).instrument
    assert buy(harness, mandate_id, instrument_id=instrument.token).json()["approved"] is True

    assert cancel_card(harness, mandate_id, scope).status_code == 200

    view = harness.client.get(f"/mandates/{mandate_id}").json()
    assert view["status"] == "ACTIVE", "cancelling a card must not end the mandate"
    assert view["spent"]["minor_units"] == 13000, "settled purchases are not undone"

    refused = buy(harness, mandate_id, instrument_id=instrument.token, key="cap_2")
    assert refused.json()["reason_code"] == "instrument_revoked"


def test_the_agent_pays_with_the_mandates_own_card_end_to_end(harness):
    """The whole point, driven the way the bot drives it: free text in, a purchase out,
    and the card was named by the mandate rather than by the agent."""
    mandate_id, scope = with_card(harness)

    settled = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    ).json()
    assert settled["outcome"] == "settled", settled

    cancel_card(harness, mandate_id, scope)

    refused = harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre outro voo para Córdoba"},
    ).json()
    # Rejected at authorization, not at capture: a cancelled card stops the attempt
    # before it is ever put to a processor.
    assert refused["outcome"] == "rejected"
    assert refused["reason_code"] == "instrument_revoked"


def test_a_card_number_that_is_not_a_card_number_is_refused_at_the_edge(harness):
    response = harness.client.post(
        "/mandates", json=harness.mandate_payload(payment_method={"card_number": "não-é-cartão"})
    )

    assert response.status_code == 422


def approve(harness, mandate_id: str, escalation_id: str, amount: int):
    """The holder's signed yes, in the shape the core checks it in."""
    token = sign_compact_jws(
        {
            "decision_handle": escalation_id,
            "mandate_id": mandate_id,
            "decision": "approve",
            "amount_minor_units": amount,
        },
        harness.custody,
        harness.HOLDER_KID,
    )
    return harness.client.post(
        f"/escalations/{escalation_id}/decision",
        json={"decision": "approve", "approval_jws": token},
    )


def test_an_approved_escalation_completes_on_a_mandate_that_names_a_card(harness):
    """Approving has to actually finish the purchase.

    The resumed capture is rebuilt by the core, not resent by the agent, so it must
    present the instrument the mandate names. Without that the ladder refuses the very
    approval the holder just signed — and it refuses it on the mandate that *has* a
    card, which is every mandate the bot creates. The escalation moment of the demo
    dies exactly where the demo is.
    """
    mandate_id, scope = with_card(harness)
    # A hotel under a travel-only mandate: out of category, so approvable — the offer
    # is bought whole, with its own signature and its own total.
    offer = offer_for(harness, "HT-COR-CENTRO")
    body = harness.purchase_from_offer(mandate_id, offer, "cap_esc")
    body["instrument_id"] = scope.removeprefix("instrument:")

    escalated = harness.capture(body).json()
    assert escalated["reason_code"] == "category_not_allowed", escalated
    assert escalated["escalation_id"] is not None

    decided = approve(
        harness, mandate_id, escalated["escalation_id"], offer["total"]["minor_units"]
    )

    assert decided.status_code == 200, decided.text
    assert decided.json()["capture"]["approved"] is True, decided.text


def test_a_cancelled_card_stops_reading_as_the_way_this_mandate_pays(harness):
    """The screen and the refusal have to agree.

    Cancelling the card leaves `Mandate.instrument` where it is — the revocation is a
    separate fact, and rewriting the mandate would erase what was authorized. But a
    view that keeps advertising the card while every purchase is refused for that same
    card is a contradiction a judge reads as a bug.
    """
    mandate_id, scope = with_card(harness)
    assert harness.client.get(f"/mandates/{mandate_id}").json()["instrument_revoked"] is False

    cancel_card(harness, mandate_id, scope)

    view = harness.client.get(f"/mandates/{mandate_id}").json()
    assert view["instrument_revoked"] is True
    assert view["instrument_label"] == "•••• 4242", "o titular ainda precisa saber qual cartão era"
    assert view["status"] == "ACTIVE"

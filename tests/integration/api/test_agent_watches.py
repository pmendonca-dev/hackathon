"""The agent that keeps watching after you stop typing.

The case's own scenario is a standing order: *"buy me a flight to Córdoba if it drops
below $150"* — and then *"the agent starts watching prices"*. Everything else in this
system answers a request; this answers nothing at all until the world changes.

That is the only place where the case's premise is literally true: the buyer is not a
person pressing pay. Nobody is at the keyboard when this fires, so every guarantee has
to hold without a human in the room — which is exactly what these tests pin down.
"""

from __future__ import annotations

from aval.security.jws import sign_compact_jws

CHEAPEST_CORDOBA = "FL-SAO-COR-0918"


def offer_for(harness, sku: str) -> dict:
    offers = harness.client.get("/merchant/offers").json()["offers"]
    return next(offer for offer in offers if offer["item"]["sku"] == sku)


def drop_price(harness, sku: str, minor_units: int):
    return harness.client.post(
        "/admin/catalog/price",
        headers=harness.operator,
        json={"sku": sku, "minor_units": minor_units},
    )


# ── the judge's price knob ──────────────────────────────────────────────────
def test_a_judge_can_drop_a_price_and_the_offer_is_still_signed(harness):
    """The knob has to move a *signed* offer, or the purchase it enables proves nothing."""
    before = offer_for(harness, CHEAPEST_CORDOBA)

    assert drop_price(harness, CHEAPEST_CORDOBA, 9500).status_code == 200

    after = offer_for(harness, CHEAPEST_CORDOBA)
    assert after["total"]["minor_units"] == 9500
    assert after["merchant_authorization"], "a repriced offer is still signed by the seller"
    assert after["terms_hash"] != before["terms_hash"], "the terms moved with the price"


def test_dropping_a_price_needs_the_operator_token(harness):
    """It changes what everyone may buy. It is not an anonymous surface."""
    response = harness.client.post(
        "/admin/catalog/price", json={"sku": CHEAPEST_CORDOBA, "minor_units": 100}
    )

    assert response.status_code == 401


# ── the standing order ──────────────────────────────────────────────────────
def register(harness, mandate_id: str, instruction: str):
    return harness.client.post(
        "/agent/watches", json={"mandate_id": mandate_id, "instruction": instruction}
    )


def tick(harness, mandate_id: str):
    return harness.client.post("/agent/watches/tick", json={"mandate_id": mandate_id})


def test_a_watch_whose_price_has_not_fallen_buys_nothing_and_keeps_waiting(harness):
    """Waiting is the behaviour, not a failure to act.

    The cheapest Córdoba fare is US$ 118. Asked for one under US$ 100, the agent has
    nothing to do — and doing nothing has to leave the mandate untouched.
    """
    mandate_id = harness.create_mandate()

    created = register(harness, mandate_id, "um voo para Córdoba abaixo de $100")
    assert created.status_code == 201, created.text

    fired = tick(harness, mandate_id).json()
    assert fired["fired"] == []
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0

    listed = harness.client.get("/agent/watches", params={"mandate_id": mandate_id}).json()
    assert [watch["status"] for watch in listed["watches"]] == ["OPEN"]


def test_when_the_price_falls_the_agent_buys_with_nobody_typing(harness):
    """The case's own scenario, and the only moment the buyer is not a person.

    Nothing about the purchase is special: it goes through the same `/authorize` and
    `/capture` a typed request reaches, and the mandate decides it the same way. What
    is new is that the decision to *try* was the agent's, and it happened because the
    world changed rather than because somebody asked.
    """
    mandate_id = harness.create_mandate()
    register(harness, mandate_id, "um voo para Córdoba abaixo de $100")
    assert tick(harness, mandate_id).json()["fired"] == [], "nada caiu ainda"

    drop_price(harness, CHEAPEST_CORDOBA, 9500)

    fired = tick(harness, mandate_id).json()["fired"]
    assert len(fired) == 1, fired
    assert fired[0]["status"] == "FIRED"
    assert fired[0]["purchase"]["outcome"] == "settled"
    assert fired[0]["purchase"]["offer"]["item"]["sku"] == CHEAPEST_CORDOBA
    assert fired[0]["settlement_reference"].startswith("psp_")
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 9500


def test_a_watch_that_bought_does_not_buy_again(harness):
    """A standing order is spent once. Ticking twice must not charge twice."""
    mandate_id = harness.create_mandate()
    register(harness, mandate_id, "um voo para Córdoba abaixo de $100")
    drop_price(harness, CHEAPEST_CORDOBA, 9500)
    tick(harness, mandate_id)

    assert tick(harness, mandate_id).json()["fired"] == []
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 9500


def revoke(harness, mandate_id: str):
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "revogado", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )
    return harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})


def test_a_revoked_mandate_stops_the_agent_that_nobody_is_watching(harness):
    """The whole thesis, demonstrated by a machine acting alone.

    The judge revokes first and drops the price after. The agent still notices, still
    tries, and is refused — so what ended is the authority, not the agent. A system
    where revocation only worked while a human was typing would not have revocation.
    """
    mandate_id = harness.create_mandate()
    register(harness, mandate_id, "um voo para Córdoba abaixo de $100")

    revoke(harness, mandate_id)
    drop_price(harness, CHEAPEST_CORDOBA, 9500)

    fired = tick(harness, mandate_id).json()["fired"]

    assert len(fired) == 1, "o agente tentou, e a tentativa tem de ser reportada"
    assert fired[0]["purchase"]["outcome"] == "rejected"
    assert fired[0]["outcome"] == "mandate_revoked"
    assert fired[0]["status"] == "FIRED", "a vigília acabou; nada mais vai passar"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_a_watch_never_outlives_the_mandate_it_depends_on(harness):
    """Authority first: a standing order cannot be scheduled past its own permission."""
    mandate_id = harness.create_mandate()

    created = register(harness, mandate_id, "um voo para Córdoba abaixo de $100").json()

    mandate = harness.client.get(f"/mandates/{mandate_id}").json()
    assert created["expires_at"][:19] == mandate["expires_at"][:19]


def test_an_expired_watch_closes_without_buying(harness):
    """The person said *until the end of the month*. After that the agent stops."""
    mandate_id = harness.create_mandate()
    register(harness, mandate_id, "um voo para Córdoba abaixo de $100")
    drop_price(harness, CHEAPEST_CORDOBA, 9500)

    # The demo clock is a judge surface; moving it past the mandate expiry ages the
    # watch with it, which is the same instant the authority ends.
    harness.client.post(
        "/admin/clock", headers=harness.operator, json={"advance_seconds": 60 * 60 * 24 * 40}
    )

    fired = tick(harness, mandate_id).json()["fired"]
    assert [entry["status"] for entry in fired] == ["EXPIRED"]
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_ticking_one_mandate_never_runs_another_persons_watches(harness):
    """One bot serves a room of judges. A tick is scoped to the mandate it names."""
    mine = harness.create_mandate()
    theirs = harness.create_mandate()
    register(harness, theirs, "um voo para Córdoba abaixo de $100")
    drop_price(harness, CHEAPEST_CORDOBA, 9500)

    assert tick(harness, mine).json()["fired"] == []
    assert harness.client.get(f"/mandates/{theirs}").json()["spent"]["minor_units"] == 0

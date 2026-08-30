"""The numbers the pitch asserts, read instead of claimed.

The decision counts here are not a parallel tally kept beside the ledger — they are
aggregates *of* the ledger, the same hash-chained trail the auditor reads. A panel that
counted separately could disagree with the trail, and then one of the two would be
lying with no way to tell which.

Only the two things the trail cannot know are counted in process: how long a decision
took, and the requests that were refused at the edge before any decision existed.
"""

from __future__ import annotations

import secrets

from aval.security.jws import sign_compact_jws


def metrics(harness) -> dict:
    response = harness.client.get("/metrics")
    assert response.status_code == 200, response.text
    return response.json()


def buy(harness, mandate_id: str, key: str = "cap_met", **overrides):
    return harness.capture(harness.purchase(mandate_id, **overrides) | {"idempotency_key": key})


def test_an_authorized_purchase_is_counted_as_authorized(harness):
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id)

    assert metrics(harness)["decisions"]["authorized"] == 1


def test_a_refusal_is_counted_under_the_reason_that_produced_it(harness):
    mandate_id = harness.create_mandate()
    buy(
        harness,
        mandate_id,
        total={"minor_units": 90000, "currency": "USD", "scale": 2},
    )

    assert metrics(harness)["reasons"]["mandate_ceiling"] == 1


def test_an_escalation_is_counted_apart_from_a_refusal(harness):
    """Three outcomes, three counters. Folding `awaiting_human` into either of the
    others would erase the distinction the whole system is built on."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id, merchant_id="andesair")

    body = metrics(harness)
    assert body["decisions"]["awaiting_human"] == 1
    assert body["decisions"]["rejected"] == 0


def test_authorized_spend_outside_the_mandate_is_zero(harness):
    """The product metric. It is money held or settled with no authorization proof
    bound to it — the same definition the dispute verdict calls AGENT_OVERREACH, so the
    footer and the arbitration cannot disagree."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id)
    buy(harness, mandate_id, key="cap_no", merchant_id="andesair")

    assert metrics(harness)["spend_outside_mandate"]["minor_units"] == 0


def test_a_replayed_signature_is_counted_at_the_edge(harness):
    """The trail never sees this one: the request is refused before a decision exists."""
    mandate_id = harness.create_mandate()
    nonce = secrets.token_hex(8)
    body = harness.purchase(mandate_id) | {"idempotency_key": "cap_rep"}
    harness.capture(body, nonce=nonce)

    harness.capture(body, nonce=nonce)

    assert metrics(harness)["edge_refusals"]["signature_replayed"] == 1


def test_a_decision_is_timed(harness):
    mandate_id = harness.create_mandate()
    harness.authorize(harness.purchase(mandate_id))

    latency = metrics(harness)["latency_ms"]["authorize"]
    assert latency["count"] == 1
    assert latency["p99"] >= 0


def test_the_panel_names_no_buyer_and_no_mandate(harness):
    """A footer visible during the demo is a surface like any other."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id)

    raw = harness.client.get("/metrics").text

    assert mandate_id not in raw
    assert "usr_marta" not in raw


def test_a_settled_payment_and_one_left_in_doubt_are_counted_apart(harness):
    mandate_id = harness.create_mandate(
        limit={"minor_units": 100000, "currency": "USD", "scale": 2}
    )
    buy(harness, mandate_id, key="cap_ok", checkout_id="chk_ok")
    harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "offline"})
    buy(harness, mandate_id, key="cap_doubt", checkout_id="chk_doubt")

    payments = metrics(harness)["payments"]
    assert payments["settled"] == 1
    assert payments["in_doubt"] == 1


def test_a_revoked_mandate_shows_up_as_a_refusal_and_not_as_an_escalation(harness):
    mandate_id = harness.create_mandate()
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
    buy(harness, mandate_id)

    body = metrics(harness)
    assert body["reasons"]["mandate_revoked"] == 1
    assert body["decisions"]["awaiting_human"] == 0


def test_the_route_the_judge_actually_presses_is_timed(harness):
    """`/authorize` and `/capture` are the machine lanes. The console and the bot drive
    `/agent/purchase`, and the agent inside it calls the core in process — so timing
    only the machine lanes leaves the footer reading nearly zero during a live demo,
    which is when the number is being looked at."""
    mandate_id = harness.create_mandate()

    harness.client.post(
        "/agent/purchase",
        json={"mandate_id": mandate_id, "instruction": "compre um voo para Córdoba abaixo de $150"},
    )

    assert metrics(harness)["latency_ms"]["agent_purchase"]["count"] == 1

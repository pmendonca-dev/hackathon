from __future__ import annotations

from datetime import timedelta

from aval.security.jws import sign_compact_jws


def test_creating_a_mandate_returns_its_identifiers(harness):
    response = harness.client.post("/mandates", json=harness.mandate_payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mandate_id"].startswith("mandate_")
    assert body["policy_version"] == 1
    assert body["revocation_id"].startswith("rev_")


def test_a_mandate_without_allowed_categories_is_refused(harness):
    response = harness.client.post("/mandates", json=harness.mandate_payload(allowed_categories=[]))

    assert response.status_code == 422


def test_a_mandate_ceiling_in_another_currency_is_refused(harness):
    response = harness.client.post(
        "/mandates",
        json=harness.mandate_payload(ceiling={"minor_units": 50000, "currency": "BRL", "scale": 2}),
    )

    assert response.status_code == 422


def test_an_in_scope_purchase_is_authorized(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id))

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "authorized"
    assert response.json()["reason_code"] == "authorized"


def test_a_purchase_from_another_merchant_escalates_instead_of_passing(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id, merchant_id="other_shop")
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "awaiting_human"
    assert response.json()["reason_code"] == "merchant_out_of_scope"


def test_a_purchase_outside_the_allowed_categories_escalates(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id, category="lodging")
    )

    assert response.json()["decision"] == "awaiting_human"
    assert response.json()["reason_code"] == "category_not_allowed"


def test_a_purchase_above_the_ceiling_is_rejected_and_offers_no_approval(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(
            mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}
        ),
    )

    assert response.json()["decision"] == "rejected"
    assert response.json()["reason_code"] == "mandate_ceiling"


def test_an_unknown_mandate_is_rejected_not_crashed(harness):
    response = harness.authorize(harness.purchase("mandate_nope"))

    assert response.status_code == 200
    assert response.json()["reason_code"] == "mandate_not_found"


def test_a_fractional_amount_never_reaches_the_core(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(
            mandate_id, total={"minor_units": 130.5, "currency": "USD", "scale": 2}
        ),
    )

    assert response.status_code == 422


def test_a_whole_float_amount_is_also_refused(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(
            mandate_id, total={"minor_units": 130.0, "currency": "USD", "scale": 2}
        ),
    )

    assert response.status_code == 422


def test_mandate_expiry_is_read_as_a_real_instant_not_a_local_wall_clock(harness):
    # 13:00 at UTC+3 is 10:00 UTC, already past for this harness clock (12:00 UTC).
    mandate_id = harness.create_mandate(expires_at="2026-08-29T13:00:00+03:00")

    response = harness.authorize(harness.purchase(mandate_id))

    assert response.json()["reason_code"] == "mandate_expired"


def test_capture_settles_once_and_replays_the_same_body_for_the_same_key(harness):
    mandate_id = harness.create_mandate()
    body = harness.purchase(mandate_id) | {"idempotency_key": "cap_1"}

    first = harness.capture(body)
    replay = harness.capture(body)

    assert first.status_code == 200, first.text
    assert first.json()["approved"] is True
    assert replay.json() == first.json()


def test_reusing_an_idempotency_key_with_another_body_is_refused(harness):
    mandate_id = harness.create_mandate()
    harness.capture(harness.purchase(mandate_id) | {"idempotency_key": "cap_2"})

    response = harness.capture(harness.purchase(mandate_id, total={"minor_units": 9000, "currency": "USD", "scale": 2})
        | {"idempotency_key": "cap_2"},
    )

    assert response.json()["approved"] is False
    assert response.json()["reason_code"] == "idempotency_key_reused"


def test_a_live_limit_change_binds_the_very_next_decision(harness):
    mandate_id = harness.create_mandate()

    changed = harness.change_limit(mandate_id, 10000)

    assert changed.status_code == 200, changed.text
    assert changed.json()["policy_version"] == 2
    decision = harness.authorize(harness.purchase(mandate_id)).json()
    assert decision["reason_code"] == "budget_exceeded"


def test_a_live_limit_change_cannot_lift_the_ceiling(harness):
    mandate_id = harness.create_mandate()

    harness.change_limit(mandate_id, 100000)

    decision = harness.authorize(harness.purchase(
            mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}
        ),
    ).json()
    assert decision["reason_code"] == "mandate_ceiling"


def test_a_signed_revocation_blocks_the_next_purchase(harness):
    mandate_id = harness.create_mandate()
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )

    revoked = harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": token})

    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"revoked": True, "epoch": 1}
    decision = harness.authorize(harness.purchase(mandate_id)).json()
    assert decision["reason_code"] == "mandate_revoked"


def test_a_revocation_signed_by_a_stranger_is_refused(harness):
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("attacker_k1")
    forged = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "takeover", "epoch": 1},
        harness.custody,
        "attacker_k1",
    )

    response = harness.client.post(f"/mandates/{mandate_id}/revocation", json={"token": forged})

    assert response.status_code == 400
    assert response.json()["reason_code"] == "revocation_authority_unknown"
    decision = harness.authorize(harness.purchase(mandate_id)).json()
    assert decision["decision"] == "authorized"


def test_a_revocation_with_a_tampered_payload_is_refused(harness):
    mandate_id = harness.create_mandate()
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )
    header, payload, signature = token.split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]

    response = harness.client.post(
        f"/mandates/{mandate_id}/revocation", json={"token": f"{header}.{flipped}.{signature}"}
    )

    assert response.status_code == 400
    decision = harness.authorize(harness.purchase(mandate_id)).json()
    assert decision["decision"] == "authorized"


def test_a_revocation_cannot_be_replayed_onto_another_mandate(harness):
    victim = harness.create_mandate()
    other = harness.create_mandate()
    token = sign_compact_jws(
        {"mandate_id": victim, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )

    response = harness.client.post(f"/mandates/{other}/revocation", json={"token": token})

    assert response.status_code == 400
    decision = harness.authorize(harness.purchase(other)).json()
    assert decision["decision"] == "authorized"


def test_the_clock_moving_past_the_expiry_ends_the_mandate(harness):
    mandate_id = harness.create_mandate(expires_at="2026-08-29T18:00:00Z")
    before = harness.authorize(harness.purchase(mandate_id)).json()
    assert before["decision"] == "authorized"

    harness.clock.advance(timedelta(hours=7))

    after = harness.authorize(harness.purchase(mandate_id)).json()
    assert after["reason_code"] == "mandate_expired"


def test_a_second_mandate_under_the_same_holder_key_can_still_be_revoked(harness):
    """A person who renews a mandate keeps the same key. Revoking the newer one must
    work, and must leave the older one alone."""
    first = harness.create_mandate()
    second = harness.create_mandate()
    token = sign_compact_jws(
        {"mandate_id": second, "scope": "mandate", "reason": "holder_request", "epoch": 1},
        harness.custody,
        harness.HOLDER_KID,
    )

    revoked = harness.client.post(f"/mandates/{second}/revocation", json={"token": token})

    assert revoked.status_code == 200, revoked.text
    assert harness.client.get(f"/mandates/{second}").json()["status"] == "REVOKED"
    assert harness.client.get(f"/mandates/{first}").json()["status"] == "ACTIVE"
    assert harness.authorize(harness.purchase(second)).json()["reason_code"] == "mandate_revoked"
    assert harness.authorize(harness.purchase(first)).json()["decision"] == "authorized"

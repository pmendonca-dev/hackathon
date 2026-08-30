from __future__ import annotations


def buy(harness, mandate_id: str, key: str = "cap_psp"):
    return harness.capture(harness.purchase(mandate_id) | {"idempotency_key": key})


def set_psp(harness, mode: str):
    response = harness.client.post("/admin/psp", headers=harness.operator, json={"mode": mode})
    assert response.status_code == 200, response.text
    return response


def test_a_declined_settlement_frees_the_budget_again(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "decline")

    response = buy(harness, mandate_id)

    assert response.json()["approved"] is False
    assert response.json()["reason_code"] == "settlement_declined"
    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] == 0


def test_an_unreachable_processor_is_not_a_refusal(harness):
    """A timeout leaves the money held, never released. Releasing early is how a demo
    double-spends a purchase that actually settled on the other side."""
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")

    response = buy(harness, mandate_id)

    assert response.status_code == 502
    assert response.json()["reason_code"] == "settlement_unreachable"
    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] == 13000


def test_reconciling_after_the_processor_returns_settles_what_was_held(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)

    set_psp(harness, "online")
    reconciled = harness.client.post("/reconcile", headers=harness.operator)

    assert reconciled.json()["settled"] == 1
    assert reconciled.json()["released"] == 0
    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] == 13000
    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    assert entries[-1]["event_type"] == "purchase_settled"


def test_reconciling_a_purchase_the_processor_refused_frees_the_budget(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)

    set_psp(harness, "decline")
    reconciled = harness.client.post("/reconcile", headers=harness.operator)

    assert reconciled.json()["released"] == 1
    assert harness.read_mandate(mandate_id).json()["spent"]["minor_units"] == 0


def test_reconciling_twice_settles_nothing_the_second_time(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "offline")
    buy(harness, mandate_id)
    set_psp(harness, "online")
    harness.client.post("/reconcile", headers=harness.operator)

    again = harness.client.post("/reconcile", headers=harness.operator)

    assert again.json() == {"settled": 0, "released": 0, "pending": 0}


def test_the_processor_mode_is_read_on_every_call(harness):
    mandate_id = harness.create_mandate()
    set_psp(harness, "decline")
    first = buy(harness, mandate_id, "cap_a")

    set_psp(harness, "online")
    second = buy(harness, mandate_id, "cap_b")

    assert first.json()["approved"] is False
    assert second.json()["approved"] is True


def test_an_unknown_processor_mode_is_refused(harness):
    assert harness.client.post(
        "/admin/psp", headers=harness.operator, json={"mode": "chaos"}
    ).status_code == 422


def test_a_dispute_over_a_settled_purchase_resolves_for_the_mandate(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]

    opened = harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "Eu nunca autorizei isso",
            "authorization_jws": harness.read_token(),
        }
    )
    resolved = harness.client.post(
        f"/disputes/{opened.json()['dispute_id']}/resolution", json={"authorization_jws": harness.read_token()}
    )

    assert opened.status_code == 201, opened.text
    assert resolved.json()["status"] == "MANDATE_HELD"
    assert "prova" in resolved.json()["resolution"].lower()


def test_a_dispute_over_an_unknown_purchase_is_refused(harness):
    response = harness.client.post(
        "/disputes",
        json={
            "reservation_id": "rsv_nope",
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    )

    assert response.status_code == 404
    assert response.json()["reason_code"] == "reservation_not_found"


def test_a_dispute_is_resolved_only_once(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    dispute_id = harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    ).json()["dispute_id"]
    harness.client.post(
        f"/disputes/{dispute_id}/resolution", json={"authorization_jws": harness.read_token()}
    )

    again = harness.client.post(
        f"/disputes/{dispute_id}/resolution", json={"authorization_jws": harness.read_token()}
    )

    assert again.status_code == 409
    assert again.json()["reason_code"] == "dispute_already_resolved"


def test_the_dispute_and_its_resolution_are_on_the_trail(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    dispute_id = harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    ).json()["dispute_id"]
    harness.client.post(
        f"/disputes/{dispute_id}/resolution", json={"authorization_jws": harness.read_token()}
    )

    types = [
        entry["event_type"]
        for entry in harness.client.get(
            "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
        ).json()["entries"]
    ]
    assert types[-2:] == ["dispute_opened", "dispute_resolved"]


def test_the_trail_still_verifies_after_a_dispute(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    dispute_id = harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    ).json()["dispute_id"]
    harness.client.post(
        f"/disputes/{dispute_id}/resolution", json={"authorization_jws": harness.read_token()}
    )

    assert harness.client.get("/ledger/verify", params={"mandate_id": mandate_id}).json()["intact"]


def test_disputes_can_be_listed_for_a_mandate(harness):
    mandate_id = harness.create_mandate()
    reservation_id = buy(harness, mandate_id).json()["reservation_id"]
    harness.client.post(
        "/disputes",
        json={
            "reservation_id": reservation_id,
            "reason": "não reconheço",
            "authorization_jws": harness.read_token(),
        }
    )

    listed = harness.client.get(
        "/disputes",
        params={"mandate_id": mandate_id},
        headers={"X-Aval-Authorization": harness.read_token()},
    ).json()

    assert len(listed["disputes"]) == 1
    assert listed["disputes"][0]["status"] == "OPEN"

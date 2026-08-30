from __future__ import annotations

from aval.security.jws import sign_compact_jws


def instruct(harness, mandate_id: str, instruction: str):
    return harness.client.post(
        "/agent/purchase", json={"mandate_id": mandate_id, "instruction": instruction}
    )


def test_the_agent_finds_and_buys_a_flight_inside_the_mandate(harness):
    mandate_id = harness.create_mandate()

    response = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["outcome"] == "settled", body
    assert body["offer"]["item"]["sku"] == "FL-SAO-COR-0917"
    assert body["settlement_reference"].startswith("psp_")
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 13000


def test_the_agent_holds_its_own_target_price(harness):
    mandate_id = harness.create_mandate()

    response = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $100")

    assert response.json()["outcome"] == "no_offer"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 0


def test_the_agent_cannot_talk_its_way_past_the_ceiling(harness):
    mandate_id = harness.create_mandate()

    response = instruct(harness, mandate_id, "compre a executiva para Córdoba de $900")

    body = response.json()
    assert body["outcome"] == "rejected"
    assert body["reason_code"] == "mandate_ceiling"
    assert body["escalation_id"] is None, "a ceiling refusal must offer no approval path"


def test_the_agent_asking_for_a_hotel_is_escalated_not_served(harness):
    mandate_id = harness.create_mandate()

    response = instruct(harness, mandate_id, "reserve um hotel em Córdoba")

    body = response.json()
    assert body["outcome"] == "awaiting_human"
    assert body["reason_code"] == "category_not_allowed"
    assert body["escalation_id"].startswith("dh_")


def test_buying_again_runs_into_the_accumulated_budget(harness):
    mandate_id = harness.create_mandate()
    instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    second = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    assert second.json()["reason_code"] == "budget_exceeded"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["spent"]["minor_units"] == 13000


def test_a_revoked_mandate_stops_the_agent(harness):
    mandate_id = harness.create_mandate()
    harness.client.post(
        f"/mandates/{mandate_id}/revocation",
        json={
            "token": sign_compact_jws(
                {"mandate_id": mandate_id, "scope": "mandate", "reason": "holder", "epoch": 1},
                harness.custody,
                harness.HOLDER_KID,
            )
        },
    )

    response = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    assert response.json()["outcome"] == "rejected"
    assert response.json()["reason_code"] == "mandate_revoked"


def test_a_live_limit_change_binds_the_agent_without_a_restart(harness):
    mandate_id = harness.create_mandate()
    harness.change_limit(mandate_id, 10000)

    response = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    assert response.json()["reason_code"] == "budget_exceeded"


def test_the_trail_names_the_agent_that_bought(harness):
    mandate_id = harness.create_mandate()
    instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    bought = [entry for entry in entries if entry["event_type"] == "purchase_authorized"]
    assert bought[0]["detail"]["agent_id"] == "agent_aval_demo"


def test_an_untrusted_agent_profile_stops_every_purchase(harness):
    mandate_id = harness.create_mandate()
    profile = harness.client.get("/agent/profile").json()
    harness.client.post(
        "/agents",
        headers=harness.operator,
        json={
            "id": profile["agent_id"],
            "profile_url": profile["profile_url"],
            "public_jwk": profile["public_jwk"],
            "trusted": False,
        },
    )

    response = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150")

    assert response.status_code == 403
    assert response.json()["reason_code"] == "profile_not_trusted"


def test_the_purchase_the_agent_made_verifies_at_the_merchant(harness):
    mandate_id = harness.create_mandate()
    run = instruct(harness, mandate_id, "compre um voo para Córdoba abaixo de $150").json()

    verification = harness.client.post(
        "/merchant/verify",
        json={
            "authorization_proof": run["authorization_proof"],
            "merchant_authorization": run["offer"]["merchant_authorization"],
        },
    )

    assert verification.json()["accepted"] is True, verification.text

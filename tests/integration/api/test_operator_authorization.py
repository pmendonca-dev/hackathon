from __future__ import annotations

from aval.security.jws import sign_compact_jws


def test_registering_an_agent_needs_the_operator_token(harness):
    response = harness.client.post(
        "/agents",
        json={
            "id": "agent_attacker",
            "profile_url": "https://evil.example/agent",
            "public_jwk": harness.custody.public_jwk(harness.HOLDER_KID),
            "trusted": True,
        },
    )

    assert response.status_code == 401
    assert response.json()["reason_code"] == "operator_token_missing"


def test_a_wrong_operator_token_is_refused(harness):
    response = harness.client.post(
        "/agents",
        headers={"X-Aval-Operator": "not-the-token"},
        json={
            "id": "agent_attacker",
            "profile_url": "https://evil.example/agent",
            "public_jwk": harness.custody.public_jwk(harness.HOLDER_KID),
            "trusted": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "operator_token_invalid"


def test_an_agent_cannot_claim_a_key_id_another_profile_already_uses(harness):
    """Shadowing a registered kid would let a stranger answer for the real agent."""
    profile = harness.client.get("/agent/profile").json()

    response = harness.client.post(
        "/agents",
        headers=harness.operator,
        json={
            "id": "agent_shadow",
            "profile_url": "https://evil.example/agent",
            # Same kid as the demo agent, different key material.
            "public_jwk": {**harness.custody.public_jwk(harness.HOLDER_KID), "kid": profile["kid"]},
            "trusted": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["reason_code"] == "agent_kid_already_registered"


def test_the_registered_agent_keeps_answering_for_its_own_kid(harness):
    profile = harness.client.get("/agent/profile").json()

    still = harness.client.get(f"/agents/{profile['kid']}").json()

    assert still["agent_id"] == profile["agent_id"]
    assert still["trusted"] is True


def test_changing_the_live_limit_needs_a_signed_holder_decision(harness):
    mandate_id = harness.create_mandate()

    response = harness.client.patch(
        f"/mandates/{mandate_id}/limit",
        json={"limit": {"minor_units": 100000, "currency": "USD", "scale": 2}},
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "limit_change_unsigned"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["limit"]["minor_units"] == 20000


def test_a_limit_change_signed_by_a_stranger_is_refused(harness):
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("outsider_k1")
    token = sign_compact_jws(
        {"mandate_id": mandate_id, "limit_minor_units": 100000, "currency": "USD", "scale": 2},
        harness.custody,
        "outsider_k1",
    )

    response = harness.client.patch(
        f"/mandates/{mandate_id}/limit",
        json={
            "limit": {"minor_units": 100000, "currency": "USD", "scale": 2},
            "authorization_jws": token,
        },
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "limit_change_authority_unknown"
    assert harness.client.get(f"/mandates/{mandate_id}").json()["limit"]["minor_units"] == 20000


def test_a_limit_change_signed_for_another_mandate_is_refused(harness):
    victim = harness.create_mandate()
    other = harness.create_mandate()
    token = harness.limit_token(other, 100000)

    response = harness.client.patch(
        f"/mandates/{victim}/limit",
        json={
            "limit": {"minor_units": 100000, "currency": "USD", "scale": 2},
            "authorization_jws": token,
        },
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "limit_change_mandate_mismatch"


def test_the_signed_amount_must_be_the_amount_applied(harness):
    mandate_id = harness.create_mandate()
    token = harness.limit_token(mandate_id, 30000)

    response = harness.client.patch(
        f"/mandates/{mandate_id}/limit",
        json={
            "limit": {"minor_units": 100000, "currency": "USD", "scale": 2},
            "authorization_jws": token,
        },
    )

    assert response.status_code == 403
    assert response.json()["reason_code"] == "limit_change_amount_mismatch"


def test_a_properly_signed_limit_change_still_works(harness):
    mandate_id = harness.create_mandate()

    response = harness.change_limit(mandate_id, 10000)

    assert response.status_code == 200, response.text
    assert response.json()["policy_version"] == 2
    assert harness.client.get(f"/mandates/{mandate_id}").json()["limit"]["minor_units"] == 10000


def test_the_processor_switch_needs_the_operator_token(harness):
    assert harness.client.post("/admin/psp", json={"mode": "offline"}).status_code == 401
    assert harness.client.post("/reconcile").status_code == 401
    assert harness.client.post("/admin/psp", headers=harness.operator, json={"mode": "offline"}).status_code == 200


def test_the_operator_token_comparison_does_not_leak_on_prefix(harness):
    """A prefix of the real token must be as wrong as anything else."""
    prefix = harness.operator["X-Aval-Operator"][:8]

    response = harness.client.post("/admin/psp", headers={"X-Aval-Operator": prefix}, json={"mode": "offline"})

    assert response.status_code == 403


def test_two_agents_cannot_claim_the_same_profile_url(harness):
    """A profile URL identifies one agent. The second must be told so, not crash."""
    harness.custody.generate_es256("twin_a")
    harness.custody.generate_es256("twin_b")
    shared = "https://agents.aval.local/twin"
    first = harness.client.post("/agents", headers=harness.operator, json={
        "id": "agent_twin_a", "profile_url": shared,
        "public_jwk": harness.custody.public_jwk("twin_a"), "trusted": True})

    second = harness.client.post("/agents", headers=harness.operator, json={
        "id": "agent_twin_b", "profile_url": shared,
        "public_jwk": harness.custody.public_jwk("twin_b"), "trusted": True})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["reason_code"] == "agent_profile_url_taken"


def test_re_registering_the_same_agent_updates_it(harness):
    """Rotating a key is a legitimate update of one profile, not a second profile."""
    harness.custody.generate_es256("rotate_1")
    harness.custody.generate_es256("rotate_2")
    url = "https://agents.aval.local/rotating"
    harness.client.post("/agents", headers=harness.operator, json={
        "id": "agent_rotating", "profile_url": url,
        "public_jwk": harness.custody.public_jwk("rotate_1"), "trusted": True})

    again = harness.client.post("/agents", headers=harness.operator, json={
        "id": "agent_rotating", "profile_url": url,
        "public_jwk": harness.custody.public_jwk("rotate_2"), "trusted": True})

    assert again.status_code == 201
    assert harness.client.get("/agents/rotate_2").json()["agent_id"] == "agent_rotating"

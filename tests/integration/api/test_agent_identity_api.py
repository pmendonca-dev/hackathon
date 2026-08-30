from __future__ import annotations


def test_an_unsigned_purchase_never_reaches_the_core(harness):
    mandate_id = harness.create_mandate()

    response = harness.client.post("/authorize", json=harness.purchase(mandate_id))

    assert response.status_code == 401
    assert response.json()["reason_code"] == "signature_missing"


def test_a_signed_purchase_from_a_trusted_agent_is_authorized(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id))

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "authorized"


def test_the_same_body_signed_by_another_key_is_refused(harness):
    """The impostor demo: identical request, wrong key."""
    mandate_id = harness.create_mandate()
    harness.custody.generate_es256("impostor_k1")

    response = harness.authorize(harness.purchase(mandate_id), kid="impostor_k1")

    assert response.status_code == 401
    assert response.json()["reason_code"] == "key_not_found"


def test_a_key_that_signs_for_someone_elses_profile_is_refused(harness):
    """A registered key id, but the signature was made with a different private key."""
    mandate_id = harness.create_mandate()
    harness.register_agent("agent_swapped", "swapped_k1", trusted=True)
    harness.custody.generate_es256("swapped_k1_other")

    response = harness.authorize(
        harness.purchase(mandate_id), kid="swapped_k1_other", announce_kid="swapped_k1"
    )

    assert response.status_code == 401
    assert response.json()["reason_code"] == "signature_invalid"


def test_an_untrusted_profile_is_refused(harness):
    mandate_id = harness.create_mandate()
    harness.register_agent("agent_shady", "shady_k1", trusted=False)

    response = harness.authorize(harness.purchase(mandate_id), kid="shady_k1")

    assert response.status_code == 403
    assert response.json()["reason_code"] == "profile_not_trusted"


def test_a_swapped_body_breaks_the_digest(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(
        harness.purchase(mandate_id),
        tamper=harness.purchase(mandate_id, total={"minor_units": 90000, "currency": "USD", "scale": 2}),
    )

    assert response.status_code == 401
    assert response.json()["reason_code"] == "content_digest_mismatch"


def test_a_signature_that_does_not_cover_the_body_is_refused(harness):
    mandate_id = harness.create_mandate()

    response = harness.authorize(harness.purchase(mandate_id), cover_body=False)

    assert response.status_code == 401
    assert response.json()["reason_code"] == "signature_components_insufficient"


def test_a_stale_signature_is_refused(harness):
    mandate_id = harness.create_mandate()
    long_ago = int(harness.clock.instant.timestamp()) - 3600

    response = harness.authorize(harness.purchase(mandate_id), created=long_ago)

    assert response.status_code == 401
    assert response.json()["reason_code"] == "signature_stale"


def test_a_replayed_signature_is_refused(harness):
    mandate_id = harness.create_mandate()
    body = harness.purchase(mandate_id)

    first = harness.authorize(body, nonce="fixed_nonce")
    replayed = harness.authorize(body, nonce="fixed_nonce")

    assert first.status_code == 200
    assert replayed.status_code == 401
    assert replayed.json()["reason_code"] == "signature_replayed"


def test_capture_is_signed_too(harness):
    mandate_id = harness.create_mandate()
    body = harness.purchase(mandate_id) | {"idempotency_key": "cap_signed"}

    unsigned = harness.client.post("/capture", json=body)

    assert unsigned.status_code == 401
    assert unsigned.json()["reason_code"] == "signature_missing"


def test_the_trail_records_which_agent_asked(harness):
    mandate_id = harness.create_mandate()

    harness.authorize(harness.purchase(mandate_id))

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]
    assert entries[-1]["detail"]["agent_id"] == "agent_travel"


def test_the_merchant_learns_the_agent_but_never_the_human(harness):
    mandate_id = harness.create_mandate()
    harness.capture(harness.purchase(mandate_id) | {"idempotency_key": "cap_agent"})

    response = harness.client.get("/ledger", params={"merchant_id": "vuelaya", "view": "merchant"})

    assert response.json()["entries"][0]["detail"]["agent_id"] == "agent_travel"
    assert "usr_marta" not in response.text
    assert mandate_id not in response.text
